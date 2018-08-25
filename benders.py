"""
Attach Benders suffix values to variables to allow cplex to perform Benders decomposition.
"""
from pyomo.environ import Var, Suffix, BuildAction
from fix_build_vars import fix_vars
from switch_model.util import iteritems

def define_components(m):
    # benders suffix should have 0 for master problem or n for each subproblem;
    # see https://ampl.com/products/solvers/solvers-we-sell/cplex/options/
    # and https://www.ibm.com/support/knowledgecenter/en/SSSA5P_12.7.1/ilog.odms.cplex.help/CPLEX/Parameters/topics/BendersStrategy.html
    # solve with --solver cplexamp --solver-options-string "bendersopt='' benders_strategy=2"
    # but note: subproblems must be strictly continuous or you get error 2002 (bad decomposition):
    # https://www.ibm.com/developerworks/community/forums/html/topic?id=086bfa2b-35fd-4987-aca2-1e31b7fd2413
    # https://orinanobworld.blogspot.com/2013/07/benders-decomposition-with-integer.html
    # https://groups.google.com/forum/#!topic/aimms/OsMHRV-HXhk
    m.benders = Suffix(direction=Suffix.EXPORT)

    def rule(m):
        # place all build vars in the master problem (0), others in subproblem (1)
        for var in m.component_objects(Var):
            suf = 0 if var.name in fix_vars else 1
            for obj in var.values():
                m.benders[obj] = suf
    m.Assign_Benders_Suffixes = BuildAction(rule=rule)

    # # more complete decomposition, not tested
    # # assigns all build vars (actually all vars indexed by a period) to the master problem,
    # # and all vars indexed by a timeseries or timepoint to a subproblem for that timeseries.
    # # solve with --solver cplexamp --solver-options-string "bendersopt='' benders_strategy=1"
    # idx_subproblem = dict(
    #     # everything indexed by period goes in the master problem
    #     [(p, 0) for p in m.PERIODS]
    #     # one subproblem per timeseries
    #     + [(ts, ts) for ts in m.TIMESERIES]
    #     # vars for each timepoint get assigned to their timeseries subproblem
    #     + [(tp, m.tp_ts[tp]) for tp in m.TIMEPOINTS]
    # )
    # inf = float('inf')
    # for var in m.component_objects(Var):
    #     for idx, obj in iteritems(var):
    #         sub = max(idx_subproblem.get(i, 0) for i in idx)
    #         m.benders[obj] = sub
