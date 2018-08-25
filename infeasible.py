from pyomo.environ import *

def define_components(m):
    m.Infeasible = Constraint(rule = lambda m: m.BuildGen[m.BuildGen.index_set().keys()[0]] <= -1)
