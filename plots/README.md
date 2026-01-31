# AQM_CCA

Experiments designed to run on the **FABRIC** testbed to evaluate the performance of different **Active Queue Management (AQM)** algorithms and **TCP Congestion Control Algorithms (CCAs)** under controlled network conditions. :contentReference[oaicite:1]{index=1}

---

## What this repository contains

At the repository root you’ll find three primary Jupyter notebooks and supporting directories: :contentReference[oaicite:3]{index=3}

- **`create_topology.ipynb`**  
  Creates and configures the experiment topology on FABRIC (nodes, links, addressing/routing, and baseline setup). :contentReference[oaicite:4]{index=4}

- **`run_experiments.ipynb`**  
  Runs experiment trials for selected AQM/CCA combinations, collects logs/metrics, and stores outputs. :contentReference[oaicite:5]{index=5}

- **`inter-protocol.ipynb`**  
  Runs or analyzes experiments that compare behavior across protocols/CCAs (for example, “fairness” or coexistence scenarios). :contentReference[oaicite:6]{index=6}

Supporting directories (names may evolve over time): :contentReference[oaicite:7]{index=7}

- **`scripts/`** – helper scripts invoked by notebooks (setup, traffic generation, parsing, plotting)  
- **`kernel_module/`** – kernel modules or build artifacts used to enable/extend CCAs/AQM behavior  
- **`files/`** – configuration files, templates, or auxiliary assets  
- **`results/`** – experiment outputs, logs, and processed results

---

## Prerequisites

### FABRIC access
You need a FABRIC account and permission to create slices. The easiest way to ru
