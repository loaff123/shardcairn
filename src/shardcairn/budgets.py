"""Versioned deterministic work counters; denied next work is an event."""

class BudgetStop(Exception):
    """Internal control flow: retain the last complete feasible incumbent."""


class Budget:
    def __init__(self, work_limit, local_limit, node_limit):
        self.work_limit = work_limit
        self.local_limit = local_limit
        self.node_limit = node_limit
        self.used = self.local = self.nodes = 0
        self.events = []

    def deny(self, phase, budget):
        event = {'phase': phase, 'budget': budget}
        if event not in self.events:
            self.events.append(event)
        raise BudgetStop

    def tick(self, phase):
        if self.used == self.work_limit:
            self.deny(phase, 'primitive_work')
        self.used += 1

    def local_start(self):
        if self.local == self.local_limit:
            self.deny('local', 'local_candidates')
        if self.used == self.work_limit:
            self.deny('local', 'primitive_work')
        self.local += 1
        self.used += 1

    def node_start(self):
        if self.nodes == self.node_limit:
            self.deny('exact', 'exact_nodes')
        self.nodes += 1

    @property
    def primitive_denied(self):
        return any(e['budget'] == 'primitive_work' for e in self.events)

    def document(self, local_state):
        return {'primitive_work_limit': self.work_limit,
                'local_candidate_limit': self.local_limit,
                'exact_node_limit': self.node_limit,
                'primitive_work_used': self.used,
                'local_candidates_started': self.local,
                'exact_nodes_entered': self.nodes,
                'denied_budgets': [x for x in ('primitive_work', 'local_candidates', 'exact_nodes')
                                   if any(e['budget'] == x for e in self.events)],
                'local_state': local_state, 'budget_events': list(self.events)}
