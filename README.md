# Docker Introspection of Rehosted Firmware

**Author:** Diego Contreras
**Advisors:** William Oliver, Zackary Estrada

## Overview

This project explores how to introspect Docker containers inside firmware rehosted with the Penguin framework. As modern embedded systems increasingly adopt Docker to isolate services and simplify updates (e.g., BalenaOS, Home Assistant OS), the IGLOO project at MIT Lincoln Laboratory needed tools to answer questions like:

- Did the containers start in their rehosted image?
- Is the rehosted environment healthy enough to be considered trustworthy?
- What information can be extracted through Docker introspection?

The goal was to design and test a Docker introspection mechanism for Penguin, and evaluate how well IGLOO can support containerized firmware.

## The Introspection Plugin

I developed a Python-based Penguin plugin that performs Docker introspection by examining Linux kernel features that Docker relies on:

- **cgroups** - Used by Docker to control how much CPU, memory, and network bandwidth a container can use
- **namespaces** - Used by Docker to isolate containers, making processes believe they're in their own operating system

The plugin works by:
1. Reading `/proc/<pid>/ns/pid` to get a list of all processes within a container
2. Examining `/proc/<pid>/status` to get process names and PID mappings across namespaces
3. Walking `/proc/*/cgroup` to map container IDs to their cgroup v2 paths
4. Traversing `/sys/fs/cgroup` to aggregate all host PIDs associated with a container

This approach was chosen over the Docker REST API to provide maximum detail about container state.

## Case Studies

### BalenaOS
Tested on NVIDIA Jetson Xavier images. The Docker daemon never started due to systemd-related boot issues in the rehosted environment, preventing container introspection.

### Home Assistant OS
The multi-partition disk layout (boot, root, data partitions) conflicted with fw2tar's single-partition assumption, causing boot failures before Docker could even start.

## Key Findings

Two technical challenges must be addressed before Docker introspection can work at scale:

1. **Systemd support** - Many containerized firmware images use systemd to manage the Docker daemon, requiring advanced configuration to boot correctly in Penguin
2. **Multi-partition support** - Both fw2tar and Penguin assume single-partition firmware, limiting support for systems like Raspberry Pi and HAOS

## Future Work

- Build a minimal Docker testbed using a tailored Gentoo system
- Extend the plugin to map container IDs to image IDs, command lines, and health metrics
- Export results as structured JSON for integration with Penguin's logging tools
- Improve Penguin's handling of systemd and multi-partition images

---

Read more in the attached research report: [6.UR Final Research Report.pdf](6.UR%20Final%20Research%20Report.pdf)
