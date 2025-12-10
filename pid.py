#!/usr/bin/env python3
import os
from typing import List, Optional

CG2_ROOT = "/sys/fs/cgroup"


def list_container_pids_and_names(container_host_pid: int):
    """
    Return a list of (container_pid, name) for every process that shares
    the PID namespace of `container_host_pid`.

    Only /proc pseudo-files are used (no external commands).

    Parameters
    ----------
    container_host_pid : int
        A host PID for any process inside the target container (e.g. its init).

    Returns
    -------
    list[tuple[int, str]]
        Sorted by container PID ascending.

    Notes
    -----
    - This enumerates processes in the SAME PID namespace as `container_host_pid`.
      If a process spawned a *child* PID namespace, those child-namespace processes
      are not included (they're rare in typical Docker use).
    - “name” is taken from /proc/<pid>/status (`Name:`), falling back to /proc/<pid>/comm.
    """
    proc_base = "/proc"
    ref = str(container_host_pid)

    # Verify the reference PID exists and capture its PID-namespace handle
    try:
        ref_ns = os.readlink(f"{proc_base}/{ref}/ns/pid")  # e.g., "pid:[4026532xxx]"
    except FileNotFoundError:
        raise ValueError(f"Host PID {container_host_pid} does not exist in /proc")
    except PermissionError as e:
        raise PermissionError(f"Insufficient permissions to read /proc/{ref}/ns/pid: {e}")

    results = []

    for entry in os.listdir(proc_base):
        if not entry.isdigit():
            continue
        pid_path = f"{proc_base}/{entry}"
        try:
            # Match processes that are in the same PID namespace
            if os.readlink(f"{pid_path}/ns/pid") != ref_ns:
                continue

            # Read Name and container-visible PID from /proc/<pid>/status
            name = None
            cpid = None
            with open(f"{pid_path}/status", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    # Process name
                    if line.startswith("Name:"):
                        name = line.split(":", 1)[1].strip()
                    # NSpid: last number is the PID as seen in this namespace
                    elif line.startswith("NSpid:"):
                        parts = line.split()[1:]
                        if parts:
                            cpid = int(parts[-1])  # same-namespace ⇒ last element is container PID
                        # We can break early once we've seen both lines
                        if name is not None and cpid is not None:
                            break

            if name is None:
                # Fallback if /proc/<pid>/status didn't have Name (very rare)
                with open(f"{pid_path}/comm", "r", encoding="utf-8", errors="ignore") as f:
                    name = f.read().strip()

            if cpid is None:
                # If NSpid is missing (uncommon), skip; we only want container-view PIDs
                continue

            results.append((cpid, name))

        except FileNotFoundError:
            # Process may have exited during iteration; skip
            continue
        except PermissionError:
            # Lacking permission for some processes; skip them
            continue
        except OSError:
            # Other transient /proc races; skip
            continue

    results.sort(key=lambda t: t[0])
    return results



def _ensure_cgroup_v2() -> None:
    """
    Raise if the machine is not using a unified (v2) cgroup mount.
    """
    if not os.path.exists(os.path.join(CG2_ROOT, "cgroup.controllers")):
        raise RuntimeError("This host does not appear to be using cgroup v2 (unified).")


def _read_cg2_path_from_proc_cgroup(pid: str) -> Optional[str]:
    """
    From /proc/<pid>/cgroup, return the cgroup v2 path (the part after '0::'),
    or None if not present.
    """
    try:
        with open(f"/proc/{pid}/cgroup", "r") as f:
            for line in f:
                # cgroup v2 line looks like: 0::/system.slice/docker-<id>.scope
                if line.startswith("0::"):
                    # keep leading slash to match what /proc shows
                    return line.split("::", 1)[1].strip()
    except FileNotFoundError:
        pass  # process raced away
    return None


def container_cg2_path(container_id: str) -> str:
    """
    Given a Docker container ID (full or short), return its cgroup v2 path
    (as shown in /proc/<pid>/cgroup), e.g. '/system.slice/docker-<id>.scope'
    or '/docker/<id>' depending on host setup (systemd vs non-systemd, rootless, etc).

    Strategy (no docker CLI):
      1) Scan /proc/*/cgroup for a v2 entry (0::/...) that contains the container ID.
      2) Validate that the resulting path exists under /sys/fs/cgroup.
      3) If multiple matches appear, pick the shortest path (most specific).
    """
    _ensure_cgroup_v2()
    cid = container_id.lower()

    candidates = []

    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        cgpath = _read_cg2_path_from_proc_cgroup(name)
        if not cgpath:
            continue
        # Common Docker patterns on cgroup v2:
        #  - .../system.slice/docker-<id>.scope
        #  - .../user.slice/.../docker-<id>.scope  (rootless)
        #  - .../docker/<id>                       (non-systemd cgroupfs driver)
        if cid in cgpath.lower():
            # confirm the directory exists under /sys/fs/cgroup
            abs_path = os.path.join(CG2_ROOT, cgpath.lstrip("/"))
            if os.path.isdir(abs_path):
                candidates.append(cgpath)

    if not candidates:
        raise FileNotFoundError(
            f"Could not find cgroup v2 path for container id '{container_id}'. "
            "Is it running on this host, and is cgroup v2 enabled?"
        )

    # Prefer the shortest (most specific) match
    best = min(candidates, key=len)
    return best


def _read_pids_from_cgroup_dir(abs_dir: str) -> List[int]:
    """
    Read PIDs from cgroup.procs in 'abs_dir'. Return [] if missing/racing.
    """
    pids: List[int] = []
    procs_file = os.path.join(abs_dir, "cgroup.procs")
    try:
        with open(procs_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
    except FileNotFoundError:
        # Directory may have disappeared if the container exited
        pass
    return pids


def _recursive_pids(abs_root: str) -> List[int]:
    """
    Recursively collect PIDs from abs_root and all sub-cgroups beneath it.
    cgroup v2 lists only tasks in the current cgroup in cgroup.procs, so we walk.
    """
    all_pids: List[int] = []
    for cur, dirs, files in os.walk(abs_root):
        all_pids.extend(_read_pids_from_cgroup_dir(cur))
    # dedupe and sort for stable output
    return sorted(set(all_pids))


def host_pids(container_id: str) -> List[int]:
    """
    Return all host PIDs that belong to the given container (recursively),
    using only cgroup v2 pseudofiles.

    Steps:
      - Resolve the container's cgroup v2 path.
      - Walk that directory under /sys/fs/cgroup and collect PIDs from each cgroup.procs.
    """
    cgpath = container_cg2_path(container_id)
    abs_root = os.path.join(CG2_ROOT, cgpath.lstrip("/"))
    if not os.path.isdir(abs_root):
        raise FileNotFoundError(f"Resolved cgroup dir does not exist: {abs_root}")
    return _recursive_pids(abs_root)


# (Optional) If you also want the host PID of the container's 'init' (PID 1 inside the container):
def host_pid_of_container_init(container_id: str) -> Optional[int]:
    """
    Find the host PID whose NSpid line says the innermost namespace PID is 1.
    Returns None if not found (e.g., very short-lived PID1).
    """
    for pid in host_pids(container_id):
        try:
            with open(f"/proc/{pid}/status", "r") as f:
                for line in f:
                    if line.startswith("NSpid:"):
                        # The last number is PID in the deepest PID namespace
                        innermost = line.split()[-1]
                        if innermost == "1":
                            return pid
        except FileNotFoundError:
            continue
    return None

# Example usage (run as root or with sufficient /proc,/sys access):
cid = "94860d9dd294"
print("cgroup v2 path:", container_cg2_path(cid))
print("host PIDs:", host_pids(cid))
print("host PID of container init (PID 1):", host_pid_of_container_init(cid))

print(list_container_pids_and_names(1420372))

