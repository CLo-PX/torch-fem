import torch

from .elements import Hexa1, Tetra1


class Solid:
    def __init__(
        self, nodes, elements, forces, displacements, constraints, C, strains=None
    ):
        self.nodes = nodes
        self.n_dofs = torch.numel(self.nodes)
        self.elements = elements
        self.n_elem = len(self.elements)
        self.forces = forces
        self.displacements = displacements
        self.constraints = constraints
        if len(elements[0]) == 8:
            self.etype = Hexa1()
        elif len(elements[0]) == 4:
            self.etype = Tetra1()
        self.C = C
        self.strains = strains

        # Compute efficient mapping from local to global indices
        self.global_indices = []
        for element in self.elements:
            indices = torch.tensor([3 * n + i for n in element for i in range(3)])
            self.global_indices.append(torch.meshgrid(indices, indices, indexing="xy"))

    def volumes(self):
        volumes = torch.zeros((self.n_elem))
        for j, element in enumerate(self.elements):
            # Perform integrations
            nodes = self.nodes[element, :]
            volume = 0.0
            for w, q in zip(self.etype.iweights(), self.etype.ipoints()):
                # Jacobian
                J = self.etype.B(q) @ nodes
                detJ = torch.linalg.det(J)
                # Volume integration
                volume += w * detJ
            volumes[j] = volume
        return volumes

    def J(self, q, nodes):
        # Jacobian and Jacobian determinant
        J = self.etype.B(q) @ nodes
        detJ = torch.linalg.det(J)
        if detJ <= 0.0:
            raise Exception("Negative Jacobian. Check element numbering.")
        return J, detJ

    def D(self, B):
        # Element strain matrix
        zeros = torch.zeros(self.etype.nodes)
        D0 = torch.stack([B[0, :], zeros, zeros], dim=-1).ravel()
        D1 = torch.stack([zeros, B[1, :], zeros], dim=-1).ravel()
        D2 = torch.stack([zeros, zeros, B[2, :]], dim=-1).ravel()
        D3 = torch.stack([zeros, B[2, :], B[1, :]], dim=-1).ravel()
        D4 = torch.stack([B[2, :], zeros, B[0, :]], dim=-1).ravel()
        D5 = torch.stack([B[1, :], B[0, :], zeros], dim=-1).ravel()
        return torch.stack([D0, D1, D2, D3, D4, D5])

    def k(self, j):
        # Perform numerical integrations for element stiffness matrix
        nodes = self.nodes[self.elements[j], :]
        k = torch.zeros((3 * self.etype.nodes, 3 * self.etype.nodes))
        for w, q in zip(self.etype.iweights(), self.etype.ipoints()):
            J, detJ = self.J(q, nodes)
            B = torch.linalg.inv(J) @ self.etype.B(q)
            D = self.D(B)
            k[:, :] += w * D.T @ self.C @ D * detJ
        return k

    def f(self, j, epsilon):
        # Compute inelastic forces (e.g. from thermal strain fields)
        nodes = self.nodes[self.elements[j], :]
        f = torch.zeros(3 * self.etype.nodes)
        for w, q in zip(self.etype.iweights(), self.etype.ipoints()):
            J, detJ = self.J(q, nodes)
            B = torch.linalg.inv(J) @ self.etype.B(q)
            D = self.D(B)
            f[:] += w * D.T @ self.C @ epsilon * detJ
        return f

    def stiffness(self):
        # Assemble global stiffness matrix
        K = torch.zeros((self.n_dofs, self.n_dofs))
        for j in range(len(self.elements)):
            K[self.global_indices[j]] += self.k(j)
        return K

    def solve(self):
        # Compute global stiffness matrix
        K = self.stiffness()

        # Compute inelastic strains (if provided)
        F = torch.zeros(self.n_dofs)
        if self.strains is not None:
            for j, eps in enumerate(self.strains):
                F[self.global_indices[j][0]] += self.f(j, eps)

        # Get reduced stiffness matrix
        con = torch.nonzero(self.constraints.ravel(), as_tuple=False).ravel()
        uncon = torch.nonzero(~self.constraints.ravel(), as_tuple=False).ravel()
        f_d = K[:, con] @ self.displacements.ravel()[con]
        K_red = K[uncon][:, uncon]
        f_red = (self.forces.ravel() - f_d + F)[uncon]

        # Solve for displacement
        u_red = torch.linalg.solve(K_red, f_red)
        u = self.displacements.clone().ravel()
        u[uncon] = u_red

        # Evaluate force
        f = K @ u

        u = u.reshape((-1, 3))
        f = f.reshape((-1, 3))
        return u, f

    @torch.no_grad()
    def plot(self, u=0.0, node_property=None, element_property=None):
        try:
            import pyvista
        except ImportError:
            raise Exception("Plotting 3D requires pyvista.")

        pyvista.set_plot_theme("document")
        pl = pyvista.Plotter()
        pl.enable_anti_aliasing("ssaa")

        # VTK cell types
        if isinstance(self.etype, Tetra1):
            cell_types = self.n_elem * [pyvista.CellType.TETRA]
        elif isinstance(self.etype, Hexa1):
            cell_types = self.n_elem * [pyvista.CellType.HEXAHEDRON]

        # VTK element list
        elements = []
        for element in self.elements:
            elements += [len(element), *element]

        # Deformed node positions
        pos = self.nodes + u

        # Create unstructured mesh
        mesh = pyvista.UnstructuredGrid(elements, cell_types, pos.tolist())

        # Plot node properties
        if node_property:
            for key, val in node_property.items():
                mesh.point_data[key] = val

        # Plot cell properties
        if element_property:
            for key, val in element_property.items():
                mesh.cell_data[key] = val

        mesh.plot(show_edges=True)
