#!/usr/bin/env python3
"""
Generate a static PNG visualization of a paper2tree DAG.

Usage:
    python visualize.py                          # auto-finds first dag.json in outputs/
    python visualize.py outputs/<paper>/dag.json # specific paper
    python visualize.py outputs/<paper>/dag.json out.png  # custom output path
"""

import json
import sys
import textwrap
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx


def load_dag(dag_path: Path) -> dict:
    with open(dag_path) as f:
        return json.load(f)


def wrap_label(text: str, width: int = 28, max_lines: int = 3) -> str:
    lines = textwrap.wrap(text, width=width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".") + "…"
    return "\n".join(lines)


def hierarchical_layout(G: nx.DiGraph, depth_map: dict[str, int]) -> dict:
    """Top-down layout: group nodes by depth, spread evenly per level."""
    levels: dict[int, list[str]] = {}
    for node_id, depth in depth_map.items():
        levels.setdefault(depth, []).append(node_id)

    # Sort nodes within each level by their topological order for readability
    try:
        topo = list(nx.topological_sort(G))
        topo_rank = {n: i for i, n in enumerate(topo)}
        for depth in levels:
            levels[depth].sort(key=lambda n: topo_rank.get(n, 0))
    except nx.NetworkXUnfeasible:
        pass

    max_depth = max(levels.keys()) if levels else 0
    pos = {}
    for depth, nodes in levels.items():
        y = 1.0 - depth / max(max_depth, 1)
        n = len(nodes)
        for i, node_id in enumerate(nodes):
            x = (i + 1) / (n + 1)
            pos[node_id] = (x, y)
    return pos


def visualize_dag(dag_path: Path, output_path: Path) -> None:
    data = load_dag(dag_path)
    paper = data["paper"]
    dag = data["dag"]
    summary = data["summary"]

    nodes = dag["nodes"]
    edges = dag["edges"]

    G = nx.DiGraph()
    node_colors: dict[str, str] = {}
    node_sizes: dict[str, float] = {}
    node_labels: dict[str, str] = {}
    depth_map: dict[str, int] = {}
    node_types: dict[str, str] = {}

    for node in nodes:
        nid = node["id"]
        G.add_node(nid)
        node_colors[nid] = node["visual"]["color"]
        # Scale matplotlib node sizes from the design sizes (48/36/24/20)
        node_sizes[nid] = (node["visual"]["size"] ** 2) * 1.8
        depth_map[nid] = node["depth"]
        node_types[nid] = node["type"]
        node_labels[nid] = wrap_label(node["label"])

    for edge in edges:
        G.add_edge(edge["source"], edge["target"], rel=edge["relationship"])

    # Layout: try graphviz dot first, fall back to manual hierarchical
    try:
        pos = nx.nx_agraph.graphviz_layout(G, prog="dot")
        # Normalize to [0,1]
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        xr = xmax - xmin or 1
        yr = ymax - ymin or 1
        pos = {n: ((x - xmin) / xr, (y - ymin) / yr) for n, (x, y) in pos.items()}
    except Exception:
        pos = hierarchical_layout(G, depth_map)

    # Figure size scales with node count
    n_nodes = len(nodes)
    width = max(16, min(30, n_nodes * 1.1))
    height = max(10, min(22, (summary["max_depth"] + 1) * 3.5))
    fig, ax = plt.subplots(figsize=(width, height))
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#0f172a")

    colors_list = [node_colors[n] for n in G.nodes()]
    sizes_list = [node_sizes[n] for n in G.nodes()]

    # Draw edges
    nx.draw_networkx_edges(
        G,
        pos,
        ax=ax,
        arrows=True,
        arrowsize=12,
        arrowstyle="-|>",
        edge_color="#475569",
        width=1.2,
        connectionstyle="arc3,rad=0.05",
        min_source_margin=18,
        min_target_margin=18,
    )

    # Draw nodes
    nx.draw_networkx_nodes(
        G,
        pos,
        ax=ax,
        node_color=colors_list,
        node_size=sizes_list,
        alpha=0.92,
        linewidths=1.5,
        edgecolors="#1e293b",
    )

    # Draw labels
    nx.draw_networkx_labels(
        G,
        pos,
        labels=node_labels,
        ax=ax,
        font_size=5.5,
        font_color="#f8fafc",
        font_family="monospace",
    )

    # Title block
    authors_str = ", ".join(paper["authors"])
    title_lines = [
        paper["title"],
        f"Authors: {authors_str}",
        (
            f"Claims: {summary['total_nodes']}  |  "
            f"Edges: {summary['total_edges']}  |  "
            f"Max depth: {summary['max_depth']}  |  "
            f"Mean validity: {summary['mean_validity_score']:.2f}  |  "
            f"High-confidence: {summary['high_confidence_nodes']}/{summary['total_nodes']}"
        ),
    ]
    ax.set_title(
        "\n".join(title_lines),
        fontsize=9,
        color="#f8fafc",
        pad=14,
        loc="left",
        fontfamily="monospace",
    )

    # Legend
    legend_patches = [
        mpatches.Patch(facecolor="#22c55e", edgecolor="#f8fafc", label="High validity (≥0.7)"),
        mpatches.Patch(facecolor="#eab308", edgecolor="#f8fafc", label="Medium validity (0.4–0.7)"),
        mpatches.Patch(facecolor="#ef4444", edgecolor="#f8fafc", label="Low validity (<0.4)"),
    ]
    type_patches = [
        mpatches.Patch(facecolor="#64748b", edgecolor="#f8fafc", label="⬤ root  (largest)"),
        mpatches.Patch(facecolor="#64748b", edgecolor="#f8fafc", label="● primary"),
        mpatches.Patch(
            facecolor="#64748b", edgecolor="#f8fafc", label="· supporting / evidence  (smallest)"
        ),
    ]
    leg1 = ax.legend(
        handles=legend_patches,
        loc="lower left",
        fontsize=7.5,
        framealpha=0.25,
        labelcolor="#f8fafc",
        facecolor="#1e293b",
        edgecolor="#334155",
        title="Node color",
        title_fontsize=7.5,
    )
    leg1.get_title().set_color("#94a3b8")
    ax.add_artist(leg1)
    leg2 = ax.legend(
        handles=type_patches,
        loc="lower right",
        fontsize=7.5,
        framealpha=0.25,
        labelcolor="#f8fafc",
        facecolor="#1e293b",
        edgecolor="#334155",
        title="Node size",
        title_fontsize=7.5,
    )
    leg2.get_title().set_color("#94a3b8")

    ax.axis("off")
    plt.tight_layout(pad=1.5)
    plt.savefig(output_path, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved: {output_path}")


def main() -> None:
    args = sys.argv[1:]

    if not args:
        outputs = Path("outputs")
        dag_files = sorted(outputs.glob("*/dag.json"))
        if not dag_files:
            print("No dag.json found in outputs/. Run `paper2tree process <url>` first.")
            sys.exit(1)
        dag_path = dag_files[0]
    else:
        dag_path = Path(args[0])

    if len(args) >= 2:
        output_path = Path(args[1])
    else:
        output_path = dag_path.parent / "visualization.png"

    if not dag_path.exists():
        print(f"File not found: {dag_path}")
        sys.exit(1)

    visualize_dag(dag_path, output_path)


if __name__ == "__main__":
    main()
