import matplotlib.pyplot as plt
import torch
from matplotlib.collections import PolyCollection
from torch import Tensor

from .base import FEM
from .elements import Quad1, Quad2, Tria1, Tria2
from .materials import Material


class Planar(FEM):
    def __init__(self, nodes: Tensor, elements: Tensor, material: Material):
        """Initialize the planar FEM problem."""

        super().__init__(nodes, elements, material)

        # Set up thickness
        self.thickness = torch.ones(self.n_elem)

        # Element type
        if len(elements[0]) == 3:
            self.etype = Tria1()
        elif len(elements[0]) == 4:
            self.etype = Quad1()
        elif len(elements[0]) == 6:
            self.etype = Tria2()
        elif len(elements[0]) == 8:
            self.etype = Quad2()
        else:
            raise ValueError("Element type not supported.")

        # Set element type specific sizes
        self.n_strains = 3
        self.n_int = len(self.etype.iweights())

        # Initialize external strain
        self.ext_strain = torch.zeros(self.n_elem, self.n_strains)

    def D(self, B: Tensor, _):
        """Element gradient operator."""
        zeros = torch.zeros(self.n_elem, self.etype.nodes)
        shape = [self.n_elem, -1]
        D0 = torch.stack([B[:, 0, :], zeros], dim=-1).reshape(shape)
        D1 = torch.stack([zeros, B[:, 1, :]], dim=-1).reshape(shape)
        D2 = torch.stack([B[:, 1, :], B[:, 0, :]], dim=-1).reshape(shape)
        return torch.stack([D0, D1, D2], dim=1)

    def compute_k(self, detJ: Tensor, DCD: Tensor):
        """Element stiffness matrix."""
        return torch.einsum("j,j,jkl->jkl", self.thickness, detJ, DCD)

    def compute_f(self, detJ: Tensor, D: Tensor, S: Tensor):
        """Element internal force vector."""
        return torch.einsum("j,j,jkl,jk->jl", self.thickness, detJ, D, S)

    @torch.no_grad()
    def plot(
        self,
        u=0.0,
        node_property=None,
        element_property=None,
        node_labels=False,
        node_markers=False,
        orientation=False,
        axes=False,
        bcs=True,
        color="black",
        alpha=1.0,
        cmap="viridis",
        linewidth=1.0,
        figsize=(8.0, 6.0),
        colorbar=False,
        vmin=None,
        vmax=None,
        title=None,
    ):
        # Compute deformed positions
        pos = self.nodes + u

        # Bounding box
        size = torch.linalg.norm(pos.max() - pos.min())

        # Set figure size
        plt.figure(figsize=figsize)

        # Color surface with interpolated nodal properties (if provided)
        if node_property is not None:
            if isinstance(self.etype, (Quad1, Quad2)):
                triangles = []
                for e in self.elements:
                    triangles.append([e[0], e[1], e[2]])
                    triangles.append([e[2], e[3], e[0]])
            else:
                triangles = self.elements[:, :3]
            plt.tricontourf(
                pos[:, 0],
                pos[:, 1],
                triangles,
                node_property,
                cmap=cmap,
                levels=100,
                alpha=alpha,
                vmin=vmin,
                vmax=vmax,
            )
            if colorbar:
                plt.colorbar()

        # Color surface with element properties (if provided)
        if element_property is not None:
            ax = plt.gca()
            if isinstance(self.etype, Tria2):
                verts = pos[self.elements[:, :3]]
            elif isinstance(self.etype, Quad2):
                verts = pos[self.elements[:, :4]]
            else:
                verts = pos[self.elements]
            pc = PolyCollection(verts, cmap=cmap)
            pc.set_array(element_property)
            ax.add_collection(pc)
            if colorbar:
                plt.colorbar(pc)
                pc.set_clim(vmin=vmin, vmax=vmax)

        # Nodes
        if node_markers:
            plt.scatter(pos[:, 0], pos[:, 1], color=color, marker="o")
            if node_labels:
                for i, node in enumerate(pos):
                    plt.annotate(i, (node[0] + 0.01, node[1] + 0.01), color=color)

        # Elements
        for element in self.elements:
            if isinstance(self.etype, Tria2):
                element = element[:3]
            if isinstance(self.etype, Quad2):
                element = element[:4]
            x1 = [pos[node, 0] for node in element] + [pos[element[0], 0]]
            x2 = [pos[node, 1] for node in element] + [pos[element[0], 1]]
            plt.plot(x1, x2, color=color, linewidth=linewidth)

        # Forces
        if bcs:
            for i, force in enumerate(self.forces):
                if torch.norm(force) > 0.0:
                    x = pos[i][0]
                    y = pos[i][1]
                    plt.arrow(
                        x,
                        y,
                        size * 0.05 * force[0] / torch.norm(force),
                        size * 0.05 * force[1] / torch.norm(force),
                        width=0.01 * size,
                        facecolor="gray",
                        linewidth=0.0,
                        zorder=10,
                    )

        # Constraints
        if bcs:
            for i, constraint in enumerate(self.constraints):
                x = pos[i][0]
                y = pos[i][1]
                if constraint[0]:
                    plt.plot(x - 0.01 * size, y, ">", color="gray")
                if constraint[1]:
                    plt.plot(x, y - 0.01 * size, "^", color="gray")

        # Material orientations
        if orientation:
            centers = pos[self.elements, :].mean(dim=1)
            dir = torch.stack(
                [torch.cos(self.phi), -torch.sin(self.phi), torch.zeros_like(self.phi)]
            ).T
            plt.quiver(
                centers[:, 0],
                centers[:, 1],
                dir[:, 0],
                dir[:, 1],
                pivot="middle",
                headlength=0,
                headaxislength=0,
                headwidth=0,
                width=0.005,
            )

        if title:
            plt.title(title)

        plt.gca().set_aspect("equal", adjustable="box")
        if not axes:
            plt.axis("off")
