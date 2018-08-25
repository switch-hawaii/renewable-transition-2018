import os
from pyomo.environ import *
from switch_model.utilities import make_iterable
from fix_build_vars import fix_var

# List of constraints and maximum amount they could be relaxed in each scenario.
# (Bounds were needed for PHA to linearize the quadratic penalty term; not used here.)
# note: these can be found semi-automatically via the following code,
# but this would need to be subfiltered to only include constraints that
# consider sums across timepoints or timeseries within the period. Then
# we still need to assign maximum relaxation manually.
# from pyomo.environ import *
# first_period = m.PERIODS.first()
# period_constraints = [
#     V.name
#     for V in instance.component_objects(Constraint)
#     if any(
#         first_period in make_iterable(idx) for idx in V.index_set()
#     )
# ]
# print period_constraints
fuel_cell_mwh_per_kg = 0.018
period_constraint_data = [
    ('Enforce_Fuel_Consumption', 2000*8760*10), # MMBtu/year in a fuel market
    ('Battery_Cycle_Limit', 500), # cycles per year
    ('RPS_Enforce', 2000*8760*10), # MWh per period
    ('RPS_Fuel_Cap', 2000*8760*10),  # MWh per period
    ('Hydrogen_Conservation_of_Mass_Annual', 2000*8760/fuel_cell_mwh_per_kg), # kg per year
    ('Max_Store_Liquid_Hydrogen', 2000*8760/fuel_cell_mwh_per_kg) # kg per year
]
relax_var_prefix = 'Relax_'

def get_period_constraints(m):
    return [
        c
        for c in (
            getattr(m, const_data[0], None)
            for const_data in period_constraint_data
        )
        if c is not None
    ]

def move_component_above(new_component, old_component):
    # move new component above old component within their parent block
    block = new_component.parent_block()
    if block is not old_component.parent_block():
        raise ValueError(
            'Cannot move component {} above {} because they are declared in different blocks.'
            .format(new_component.name, old_component.name)
        )
    old_idx = block._decl[old_component.name]
    new_idx = block._decl[new_component.name]
    if new_idx < old_idx:
        # new_component is already above old_component
        return
    else:
        # reorder components
        # see https://groups.google.com/d/msg/pyomo-forum/dLbD2ly_hZo/5-INUaECNBkJ
        # remove all components from this block
        block_components = [c[0] for c in block._decl_order]
        # import pdb; pdb.set_trace()
        for c in block_components:
            if c is not None:
                block.del_component(c)
        # move the new component above the old one
        block_components.insert(old_idx, block_components.pop(new_idx))
        # add components back to the block
        for c in block_components:
            if c is not None:
                block.add_component(c.name, c)
        # the code below does the same thing, but seems a little too undocumented
        # new_cmp_entry = block._decl_order.pop(new_idx)
        # block._decl_order.insert(old_idx, new_cmp_entry)
        # # renumber block._decl to match new indexes
        # for i in range(old_idx, new_idx+1):
        #     block._decl[block._decl_order[i][0].name] = i

def relax_var_name(constraint):
    return relax_var_prefix + constraint.name

# note: the following functions use a closure to attach the constraint name to the
# constraint function, so they may not work with PySP (which uses pickle).
# But Pyomo doesn't call the constraint rule with any information about the
# corresponding constraint object, so it is difficult to find the right component
# programmatically.
# If this doesn't work, we might have to extract the constraint reference from the
# next higher frame in the call stack.
def relax_constraint(c):
    constraint_name = c.name
    c.original_rule = c.rule
    def new_rule(m, *idx):
        expr = getattr(m, constraint_name).original_rule(m, *idx)
        if expr is not Constraint.Skip and expr is not Constraint.Infeasible:
            args = list(expr._args) # make mutable
            # add this scenario's relaxation var to the high side of the inequality (always _args[1])
            # note: this also works for equality constraints, which just need to have the same side relaxed in all cases.
            args[1] += getattr(m, relax_var_name(c))[idx]
            expr._args = type(expr._args)(args)    # convert back to original type
        return expr
    c.rule = new_rule

def define_arguments(argparser):
    argparser.add_argument(
        "--no-cross-time-duals", action='store_true',
        help="Don't save dual values of cross-timeseries (per-period) constraints. Otherwise "
             "they will be saved in a file called 'cross_time_duals.tab' in the outputs directory "
             "for use in later model runs."
    )
    argparser.add_argument(
        "--save-relaxation-bid", action='store_true',
        help="Save total cost and values of relaxation variables for "
             "cross-timeseries constraints in a file called 'relaxation_bid.tab' "
             "in the outputs directory for use in later model runs."
    )
    argparser.add_argument(
        "--add-cross-time-relaxation-variables", action='store_true',
        help="Add relaxation variables to all cross-timeseries (per-period) constraints."
    )
    argparser.add_argument(
        "--cross-time-relaxation-price-file", default=None,
        help="Name of the file holding prices to apply to relaxation variables for cross-time"
             "constraints. Uses same format as 'cross_time_duals.tab'."
    )
    argparser.add_argument(
        "--fix-cross-time-relaxation-variables", action='store_true',
        help="Set cross-time relaxation variables to fixed values stored in .tab files in the inputs dir."
    )
    argparser.add_argument(
        "--no-standard-results", action='store_true',
        help="Prevent saving of results by standard switch modules (useful for minimizing disk access)."
    )


def define_components(m):

    if not m.options.no_cross_time_duals:
        # make sure the dual suffix is defined
        if not hasattr(m, "dual"):
            m.dual = Suffix(direction=Suffix.IMPORT)

    if m.options.add_cross_time_relaxation_variables:
        # Add relaxation variables for all cross-time constraints
        for constraint_name, relax_limit in period_constraint_data:
            try:
                c = getattr(m, constraint_name)
            except AttributeError:
                continue # ignore missing constraints
            # define relaxation variables for all scenarios for all instances of this constraint
            c_idx = c.index_set()
            relax_var = Var(c_idx)
            # set bounds to avoid unbounded model when price is attached
            relax_var.relax_limit = relax_limit
            setattr(m, relax_var_name(c), relax_var)
            # make sure the relaxation variable is constructed before the constraint
            # but after the constraint's indexing set.
            move_component_above(relax_var, c)
            # relax the constraint
            relax_constraint(c)
        # apply the bounds later, after the objects are constructed
        def relax_rule(m):
            for c in get_period_constraints(m):
                var = getattr(m, relax_var_name(c))
                for v in var.itervalues():
                    v.setlb(-var.relax_limit)
                    v.setub(var.relax_limit)
        m.Set_Relaxation_Bounds = BuildAction(rule=relax_rule)


    if m.options.fix_cross_time_relaxation_variables:
        # Only used for final evaluation after slack has been allocated. The DW script stores
        # the final allocation of slack for each slice and then runs one more pass to get final
        # costs and operating state.
        # The values for the relaxation variables are slice-specific, so we look for the tab files
        # in the inputs directory for this particular slice.
        def rule(m):
            if m.options.verbose:
                print "Fixing cross-time relaxation variables with values from {}...".format(m.options.inputs_dir)
            for c in get_period_constraints(m):
                fix_var(m, getattr(m, relax_var_name(c)), m.options.inputs_dir)
        m.Fix_Cross_Time_Relaxation_Variables = BuildAction(rule=rule)

    if m.options.no_standard_results:
        # suppress standard reporting to minimize disk access (ugh)
        from importlib import import_module
        for module in [
            'balancing.load_zones', 'generators.core.build', 'generators.core.dispatch',
            'generators.extensions.storage', 'reporting'
        ]:
            imported_module = import_module('switch_model.' + module)
            try:
                del imported_module.post_solve
            except AttributeError:
                # already deleted, e.g., module persists across scenario solver runs
                pass

def define_dynamic_components(m):
    # Define alternative objective function that includes costs assigned to dual variables

    if m.options.cross_time_relaxation_price_file:
        if m.options.add_cross_time_relaxation_variables:
            assign_cross_time_relaxation_prices(m)
        else:
            raise ValueError(
                "The --cross-time-relaxation-price-file option cannot be used without "
                "the --add-cross-time-relaxation-variables option."
            )

# note: if a particular index of a constraint is set to Constraint.Skip, then
# Pyomo leaves it out of constraint.items(), so assign_cross_time_relaxation_prices()
# (below) won't look for a price for it and the post_solve() code (further below)
# won't attempt to write a dual value for it (which is good, because it probably
# doesn't have one). As a consequence, the DW model won't try to work with
# that constraint, since it uses the duals file as its basis. So it won't
# write a price for that constraint into the prices file either.
# A relaxation var will be created for this constraint item, but since there's
# no price attached to it and it isn't used to relax any constraints, Pyomo
# never sends it to the solver, and the relaxation var ends up with a None
# value, which Switch writes to the variable .tab files as ''. We watch for that
# when setting up the DW model and ignore those instances.
# It's a little brittle, but it seems to work.

def assign_cross_time_relaxation_prices(m):
    # Assign costs to the cross-time relaxation variables (used to discover how each
    # slice would respond to the proposed prices, and eventually iterate toward the
    # correct prices and quantities)
    # Note: This file has the same format as the 'cross_time_duals.tab' file created
    # by the '--save-cross-time-duals' option. The values also have the same sign
    # and magnitude as those, i.e., discounted cost per unit of relaxation (implicitly
    # per period).
    if m.options.verbose:
        print "Assigning prices to cross-time relaxation variables from {}...".format(m.options.cross_time_relaxation_price_file)
    def cost_rule(m):
        with open(m.options.cross_time_relaxation_price_file) as f:
            # read all values from the file
            rows = [r.strip().split('\t') for r in f]
            price_dict = {tuple(r[:-1]): float(r[-1]) for r in rows}
        total_cost = 0.0
        for component in get_period_constraints(m):
            var_name = relax_var_name(component)
            component_name = component.name
            for key, c in component.items():
                k = (component_name,) + tuple(str(i) for i in make_iterable(key))
                price = price_dict[k]
                var = getattr(m, var_name)[key]  # matching relaxation var
                total_cost += price * var
        return m.SystemCost + total_cost
    # note: we create a new objective function so that the standard reporting
    # methods will ignore these extra costs, and also to avoid all the discounting
    # that Switch normally does to costs (we want to use raw dual*slack values)
    m.System_Cost_With_Relaxations = Objective(rule=cost_rule, sense=minimize)
    m.Minimize_System_Cost.deactivate()

def post_solve(m, outputs_dir):
    # save any requested data
    if not m.options.no_cross_time_duals:
        # these will be applied as prices for variables.
        # each constraint/variable has different indexing, so write them in variable-length,
        # tab-separated format, with variable name, then indexes, then values
        with open(os.path.join(m.options.outputs_dir, 'cross_time_duals.tab'), 'w') as f:
            for component in get_period_constraints(m):
                constraint_name = component.name
                # note: we assume every item is indexed; otherwise we need to branch here on c.is_indexed()
                for key, c in component.items():
                    row = (constraint_name,) + tuple(make_iterable(key)) + (m.dual.get(c, None),)
                    f.write('\t'.join(map(str, row)) + '\n')

    if m.options.save_relaxation_bid:
        if not m.options.add_cross_time_relaxation_variables:
            raise ValueError(
                "The --save-relaxation-bid option cannot be used without "
                "the --add-cross-time-relaxation-variables option."
            )
        with open(os.path.join(m.options.outputs_dir, 'relaxation_bid.tab'), 'w') as f:
            for constraint in get_period_constraints(m):
                var_component = getattr(m, relax_var_name(constraint))
                for key, var_obj in var_component.items():
                    if var_obj.value is not None:   # ignore relaxation variables for skipped constraints
                        row = (constraint.name,) + tuple(make_iterable(key)) + (value(var_obj),)
                    f.write('\t'.join(map(str, row)) + '\n')
            # also save total cost
            f.write('SystemCost\t{}\n'.format(value(m.SystemCost)))
