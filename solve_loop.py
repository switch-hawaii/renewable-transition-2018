"""
TODO:
- if a job array number is passed, make solver steps use that row from scenarios.txt, otherwise default
- save evaluation scenarios in files called scenarios_eval_<scen_name>.txt
- save outputs in <outputs_dir>/slices/n, where <outputs_dir> comes from base model, e.g., outputs/high_oil
- save slice inputs in <inputs_dir>/slices/n (not inputs/slices)
"""
# process:
# - solve main model
#   - copy duals to .tab file for evaluation loop
#   - copy build vars to .tab files for evaluation loop
# - run allocation loop
# - run final evaluation
#
# allocation loop (new script):
# - save prices for cross-time relaxation variables in .tab files for all slices
# - solve models for all slices (mpirun switch solve-scenarios, so it can happen on desktop or hpc)
# - construct new bid from weighted average of total_cost.txt and .tab files for cross-time relaxation variables
# - save all bids received so far (also allow restart with saved bids)
# - solve small DW optimization problem (!) to calculate new marginal costs for relaxation variables
# - check for convergence (what are the upper and lower bounds?)
#
# after outer loop (final evaluation)
# - create .tab files for all cross-time relaxation variables in each slice, showing allocated quotas (in slice input dir)
# - turn off price terms for cross-time relaxations
# - solve models for all slices
# - calculate weighted average total cost
# - check for unserved load or unmet cross-time constraints?
#
# DW optimization problem:
# Assume any negative amount of slack is available at $0 marginal cost, and any positive amount at $max (10x standard dual price).
# This can be implemented by setting cost equal to $max * slack_positive + convex combination of prior bids, and
# setting a constraint that slack_positive-slack_negative == convex combination of prior slack bids.

# This is expected to run on a server, with access to some number of nodes and cores via mpirun

import os, sys, shutil, glob, pipes
import switch_model.solve
from allocate_period_constraints import get_period_constraints, relax_var_name
from pyomo.environ import *
from pyomo.opt import SolverStatus, TerminationCondition
import pyutilib.subprocess  # handy for running scripts with streaming output

# setup dummy model (with no data) so we can read standard settings as needed
args = switch_model.solve.get_option_file_args()
m = switch_model.solve.main(args=args, return_model=True)

# solver options for multi-thread (main model) and single-thread solutions
# we assume the existing arguments are suited for a multi-threaded solve,
# and construct a single-threaded option string based on them (may only work with cplexamp)
solver_options_multi_thread = m.options.solver_options_string
solver_options_single_thread = m.options.solver_options_string + ' threads=1'

base_dual_price_file = os.path.join(m.options.outputs_dir, 'cross_time_duals.tab')
dw_dir = 'inputs/dw'  # any way to derive this from the base model?
slices_dir = 'inputs/slices'

# total cost and slack for relaxation variables in the most recent solution
# of the slices (saved by each slice in its own outputs directory)
relaxation_bid_file = 'relaxation_bid.tab'
# record of all bids from all slices in all iteration rounds
slice_bid_file = os.path.join(dw_dir, 'cross_time_allocation_bids_per_slice.tab')
# record of average bids across all slices in all iteration rounds
bid_file = os.path.join(dw_dir, 'cross_time_allocation_bids.tab')

# DW-generated elements that are shared between slices
# Note: all DW-generated stuff is in one dir;
# removing this dir will cause the script to restart from scratch.
# TODO: put per-slice data in here too?
slice_price_file = os.path.join(dw_dir, 'relaxation_prices.tab')

# setup scenarios for slice-solving
# (assume every valid switch subdir in the slices dir is a scenario)
scenarios = sorted([
    p.split('/')[-2] for p in glob.glob('inputs/slices/*/switch_inputs_version.txt')
])
with open('scenarios.txt', 'w') as f:
    f.writelines(
        '--scenario-name {s} --inputs-dir {sd}/{s} '
        '--outputs-dir outputs/{s} '
        '--include-module fix_build_vars --fix-build-vars-source-dir {bd} '
        # '--no-cross-time-duals ' # not needed for slice solutions but interesting for diagnosis
        '--solver-options-string {so} ' # restrict to one thread so we can run many per node
        '\n'
        .format(
            s=s, sd=slices_dir, bd=m.options.outputs_dir
            so=pipes.quote(solver_options_single_thread)
        )
        for s in scenarios
    )

if not os.path.exists(dw_dir):
    os.makedirs(dw_dir)

# # automatically flush stdout and stderr (pushes data to logs faster on HPC
# # and streams results when testing in a Jupyter notebook or Atom/Hydrogen)
# class flushfile():
#     def __init__(self, f):
#         self.f = f
#     def __getattr__(self,name):
#         return object.__getattribute__(self.f, name)
#     def write(self, x):
#         self.f.write(x)
#         self.f.flush()
#     def flush(self):
#         self.f.flush()
# oldsysstdout = sys.stdout
# oldsysstderr = sys.stderr
# sys.stdout = flushfile(sys.stdout)
# sys.stderr = flushfile(sys.stderr)


# Note: solve_slices_with_duals() stores relaxation values per slice after each
# round, and aggregates up from there to write the bid_file for solve_master_model().
# Then solve_master_model writes generic files for relaxation prices and bid weights.
# Eventually solve_slices_with_fixed_relaxation uses the bid weights and granular
# bid data to write slack allocations for each slice.

def main():
    if not os.path.exists(base_dual_price_file):
        # Solve main model and store initial dual values of constraints
        # (not actually used, but they tell us which constraints are in play)
        solve_build_model()

    # main loop
    # can be restarted anytime, since state is saved on disk.
    # delete inputs/dw or just inputs/dw/iteration_step.txt to restart from scratch
    while True:
        # calculate and store relaxation prices and/or slack allocation for
        # individual slices (uses small Dantzig-Wolfe model for "supply" of slack)
        if solve_master_model():
            # returns True when converged
            break

        # solve slices then store bids (slack usage and cost) from individual
        # slices and weighted average for all slices
        solve_slices_with_duals()

        # get "bid" back
        # - construct new bid from weighted average of total_cost.txt and .tab files for cross-time relaxation variables
        # - save all bids received so far (also allow restart with saved bids)
        # - solve small DW optimization problem (!) to calculate new marginal costs for relaxation variables
        update_iteration_count()

    # After convergence, find final results
    solve_slices_with_fixed_relaxation()

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

def update_iteration_count():
    cur_count = get_iteration_count()
    print("="*80)
    print("Finished iteration {} of cross-time constraint allocation model.".format(cur_count))
    print("="*80)
    with open(os.path.join(dw_dir, 'iteration_step.txt'), 'w') as f:
        f.write(str(cur_count + 1))

def get_iteration_count():
    try:
        with open(os.path.join(dw_dir, 'iteration_step.txt')) as f:
            return int(f.read().strip())
    except IOError:
        # no counter file in place
        return 0

def run(cmd):
    # run one instance of the specified command
    return_code, output = pyutilib.subprocess.run(cmd, tee=True)
    # args = shlex.split(cmd)
    # return_code = subprocess.call(args)
    if return_code:
        raise RuntimeError('Error while running command "{}".'.format(cmd))

def mpi_run(cmd):
    # run one instance of `cmd` on each core in the current allocation
    # (depends on mpi setup)
    run('mpirun ' + cmd)

def solve_build_model():
    # solve main optimization model with current settings, and save dual values
    # (model will also automatically save build variables)
    run('switch solve --save-cross-time-duals')

def solve_master_model():
    high_prices = {
        # we assign a generic high dual price, since some of these have 0 dual in the
        # main optimization model (nonbinding)
        # k: 10*abs(v) for k, v in read_relaxation_price_file(base_dual_price_file).items()
        k: 100000.0 for k, v in read_relaxation_price_file(base_dual_price_file).items()
    }
    iteration = get_iteration_count()

    if iteration == 0:
        # first round, bids from slice solutions are not available;
        # just use generic prices
        write_relaxation_price_file(slice_price_file, high_prices)
        return False

    # read prior bids from slices (stored by solve_slices_with_duals())
    with open(bid_file) as f:
        rows = [row.strip('\n').split('\t') for row in f]
    # each row is formatted like this:
    # iteration round number, constraint name, index1, ..., indexn, quantity consumed
    # or iteration round number, SystemCost, (no indexes), cost
    # bids dict has key=(round, comma-separated constraint name, index1, ..., indexn),
    # value=slack
    bids = {}
    costs = {}
    for row in rows:
        round = int(row[0])
        key = ','.join(row[1:-1])  # convert to comma-separated string
        val = float(row[-1])
        if key == 'SystemCost':
            costs[round] = val
        else:
            bids.setdefault(round, {})[key] = val

    dw = ConcreteModel()
    dw.ROUNDS = Set(initialize=sorted(costs.keys()))
    dw.CONSTRAINTS = Set(initialize=sorted(bids[0].keys()), ordered=True)
    dw.slack = Param(dw.ROUNDS, dw.CONSTRAINTS, rule=lambda m, r, c: bids[r][c])
    dw.system_cost = Param(dw.ROUNDS, initialize=costs)
    # apply a large cost for any upward slack (should be enough to prohibit it)
    dw.relaxation_cost = Param(
        dw.CONSTRAINTS, initialize=lambda m, c: 10 * high_prices[tuple(c.split(','))]
    )
    dw.Weight = Var(dw.ROUNDS, within=PercentFraction)
    dw.Use_Convex_Weights = Constraint(
        rule=lambda dw: sum(dw.Weight[r] for r in dw.ROUNDS) == 1.0
    )
    # choose amount of up and down relaxation to do (we charge for both directions)
    dw.RelaxUp = Var(dw.CONSTRAINTS, within=NonNegativeReals)
    dw.RelaxDown = Var(dw.CONSTRAINTS, within=NonNegativeReals)
    dw.Calculate_Relaxation = Constraint(
        dw.CONSTRAINTS,
        rule=lambda dw, c:
            dw.RelaxUp[c] - dw.RelaxDown[c]
            == sum(dw.Weight[r] * dw.slack[r, c] for r in dw.ROUNDS)
    )
    # charge for system cost and relaxation
    dw.Objective = Objective(
        rule=lambda dw:
            sum(dw.Weight[r] * dw.system_cost[r] for r in dw.ROUNDS)
            + sum(dw.RelaxUp[c] * dw.relaxation_cost[c] for c in dw.CONSTRAINTS)
            + sum(dw.RelaxDown[c] * dw.relaxation_cost[c] for c in dw.CONSTRAINTS),
        sense=minimize
    )
    dw.dual = Suffix(direction=Suffix.IMPORT)
    dw.iis = Suffix(direction=Suffix.IMPORT) # in case of infeasible models

    solve_pyomo_model(dw)

    # create dictionary of current dual values for relaxed constraints
    duals = {
        tuple(idx.split(',')): dw.dual[obj]
        for idx, obj in dw.Calculate_Relaxation.iteritems()
    }

    write_relaxation_price_file(slice_price_file, duals)

    with open(os.path.join(
        dw_dir, 'expected_slack_{}.txt'.format(iteration)
    ), 'w') as f:
        f.writelines(
            '{}: {}\n'.format(c, value(dw.RelaxUp[c] - dw.RelaxDown[c]))
            for c in dw.CONSTRAINTS
        )

    # With these sharp prices for relaxation in either direction, this should
    # converge with minimal slack, so we use that as our convergence test.
    abs_slack = sum(value(dw.RelaxUp[c] + dw.RelaxDown[c]) for c in dw.CONSTRAINTS)
    if abs_slack < 100:
        # for some reason the battery slack never converges to 0 (maybe because
        # it's nonbinding or max_relax * cost is within the solver's optimization gap?).
        converged = True
        bid_weights = {round: value(weight) for round, weight in dw.Weight.items()}
        allocate_slack_to_slices(bid_weights)
    else:
        converged = False
        print(
            "Not converged after {} iterations; unallocated cross-time slack={:,.0f}."
            .format(iteration, abs_slack)
        )

    return converged

def allocate_slack_to_slices(bid_weights):
    """
    Calculate and store the allowed slack for all relaxation variables in all
    slices, using the supplied bid weights. Allowed values are stored in
    variable.tab files in the inputs directory for each slice model.
    """
    # allowed dict has key=(slice, var), val=var subdict
    # var subdict has key=idx, value=allowed slack
    allowed = dict()
    with open(slice_bid_file) as f:
        for row in f:
            items = split_tsv(row)
            iteration = int(items[0])
            slice = items[1]
            var = items[2]
            idx = items[3:-1]
            val = float(items[-1])
            var_dict = allowed.setdefault((slice, var), {})
            var_dict[idx] = var_dict.get(idx, 0.0) + bid_weights[iteration] * val
    for (slice, var), var_dict in allowed.items():
        relax_var = 'Relax_' + var # ugh, but too hard to use relax_var_name() here
        with open(os.path.join(slices_dir, slice, relax_var + '.tab'), 'w') as f:
            headers = (
                ['INDEX_'+str(i) for i in range(1, len(var_dict.keys()[0]))]
                + [relax_var]
            )
            f.write(tsv(headers))
            f.writelines(tsv(k + (v,)) for k, v in sorted(var_dict.items()))

# helper functions to parse rows separated with tabs and terminated with newlines
# TODO: replace similar code with these in various places...
def tsv(vals):
    return '\t'.join(map(str, vals)) + '\n'
def split_tsv(row):
    """Return a tuple of all items in tab-separated, newline-terminated row."""
    return tuple(row.strip('\n').split('\t'))

def solve_pyomo_model(dw):
    # Setup solver identically to Switch; we could use different settings,
    # but this is an easy way to get workable ones.
    solver = SolverFactory(m.options.solver, solver_io=m.options.solver_io)

    print("Solving pyomo model...")
    results = solver.solve(dw, options_string=solver_options_multi_thread)
    dw.solutions.load_from(results)

    if (
        results.solver.status in {SolverStatus.ok, SolverStatus.warning} and
        results.solver.termination_condition == TerminationCondition.optimal
    ):
        return
    elif (results.solver.termination_condition == TerminationCondition.infeasible):
        if hasattr(model, "iis"):
            print "Model was infeasible; irreducibly inconsistent set (IIS) returned by solver:"
            print "\n".join(c.name for c in model.iis)
        else:
            print "Model was infeasible; if the solver can generate an irreducibly inconsistent set (IIS),"
            print "more information may be available by setting the appropriate flags in the "
            print 'solver_options_string and calling this script with "--suffixes iis".'
        raise RuntimeError("Infeasible model")
    else:
        print "Solver terminated abnormally."
        print "  Solver Status: ", results.solver.status
        print "  Termination Condition: ", results.solver.termination_condition
        if model.options.solver == 'glpk' and results.solver.termination_condition == TerminationCondition.other:
            print "Hint: glpk has been known to classify infeasible problems as 'other'."
        raise RuntimeError("Solver failed to find an optimal solution.")


def read_relaxation_price_file(file):
    with open(file) as f:
        rows = tuple(r.strip().split('\t') for r in f)
    return {tuple(r[:-1]): float(r[-1]) for r in rows}

def write_relaxation_price_file(file, duals):
    with open(file, 'w') as f:
        for key, value in duals.items():
            row = key + (str(value),)
            f.write('\t'.join(row) + '\n')

def solve_slices_with_duals():
    """
    Solve slice models using previously saved relaxation prices.
    Then calculate average cost and slack values across all the slices and store
    in the bid_file.
    """
    # solve all the slices, using relaxation prices
    # note: this will save relaxation values for each slice in standard
    # outputs/nnn/VarName.tab files.
    if os.path.exists('scenario_queue'):
        shutil.rmtree('scenario_queue')
    mpi_run(
        'switch solve-scenarios '
        '--add-cross-time-relaxation-variables '
        '--cross-time-relaxation-price-file {dd}/relaxation_prices.tab '
        '--save-relaxation-bid '
        '--no-standard-results --no-save-solution '  # avoid unnecessary disk access
        '--quiet --no-stream-solver '  # avoid unnecessary log files
        .format(dd=dw_dir)
    )
    # save average values from the slack variable .tab files
    calculate_average_cost_and_slack()

def calculate_average_cost_and_slack():
    """
    Calculate average bid (slack usage and cost) for all recently solved slices.
    Save bids for individual slices in slice_bid_file and weighted average bid
    in bid_file.
    """
    slice_slack = []
    total_slack = dict()
    total_days = 0
    for s in scenarios:
        with open(os.path.join(slices_dir, s, 'timeseries.tab')) as f:
            day_count = len(f.readlines()) - 1
        total_days += day_count
        with open(os.path.join('outputs', s, relaxation_bid_file)) as f:
            for row in f:
                items = row.strip('\n').split('\t')
                key = tuple(items[:-1])  # constraint name, idx values
                slack = float(items[-1])
                slice_slack.append((s,) + key + (slack,))
                total_slack.setdefault(key, 0)
                total_slack[key] += day_count * slack

    averages = sorted(
        key + (str(val/total_days),) for key, val in total_slack.items()
    )
    # save results
    iteration = get_iteration_count()
    write_bid_file(slice_bid_file, sorted(slice_slack), iteration)
    write_bid_file(bid_file, averages, iteration)

def write_bid_file(file, bids, iteration):
    with open(file, 'a') as f:
        if iteration == 0:
            # in the first round, truncate the file if it exists already
            f.seek(0)
        f.writelines(tsv((iteration,) + row) for row in bids)

def solve_slices_with_fixed_relaxation():
    print("")
    print("="*80)
    print("Slack allocation model converged.")
    print("Performing final model runs with fixed cross-time slack for each scenario.")
    print("="*80)
    print("")
    if os.path.exists('scenario_queue'):
        shutil.rmtree('scenario_queue')
    # solve all the slices, using relaxation prices
    mpi_run(
        'switch solve-scenarios '
        '--add-cross-time-relaxation-variables '
        '--fix-cross-time-relaxation-variables '
        '--save-relaxation-bid '
    )
    # save final costs and slack in the bid file (actually may be a bad idea
    # since it shows a false bid that will mess up the plans if it re-runs?)
    calculate_average_cost_and_slack()

if __name__ == '__main__':
    main()
