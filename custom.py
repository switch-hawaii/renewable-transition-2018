from pyomo.environ import *

def define_components(m):
    def rule(m):
        for var in m.component_objects(Var):
            elements = var.values() if var.is_indexed() else [var]
            reported = False
            for v in elements:
                if v.is_binary() or v.is_integer():
                    if not reported:
                        print "relaxing integrality for variable {}".format(var)
                        reported = True
                    # based on https://projects.coin-or.org/Coopr/browser/pyomo/trunk/pyomo/core/plugins/transform/relax_integrality.py?rev=9490
                    # save the bounds, because they get reset when we change the domain
                    lb = v.lb
                    ub = v.ub
                    v.domain = Reals
                    v.setlb(lb)
                    v.setub(ub)
                    
    m.RelaxIntegrality = BuildAction(rule=rule)
