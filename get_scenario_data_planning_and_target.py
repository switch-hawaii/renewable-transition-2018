#!/usr/bin/env python

import sys, os, argparse
from textwrap import dedent

import switch_model.hawaii.scenario_data as scenario_data

###########################
# Scenario Definitions

# definitions of standard scenarios (may also specify inputs_subdir to read in alternative data)
# TODO: find a way to define the base scenario here, then apply the others as changes to it
# Maybe allow each to start with --inherit-scenario <parent>? (to one level)
# (--scenario does this already)

# Main plans, cross tested with with high/ref/low oil prices
# - Reference (optimal for EIA reference)
# - Oil pessimist (optimal for EIA high oil prices)
# - Oil optimist (optimal for EIA low oil prices)
# - PSIP plan (uses ref case inputs)
# - renewable ban (uses ref case inputs)
# - least-cost, no-policy, reference oil prices (will RPS+EV plan cost much?)
# - 2030 RPS (still 2045 EVs)
#
# LNG evaluation (all with ref oil prices):
# - 2045 RPS, force LNG tier in 2020-2045 (but don't force consumption)
# - 2045 RPS, force LNG tier in 2025-2045
# - 2030 RPS, force LNG in 2020-2030
# - 2030 RPS, force LNG in 2025-2030
# - discuss change in cost, investment plan, renewable share relative to base cases
# (note: LNG is excluded from the base, since there's currently no push for it)
# (This should be enough to show whether LNG makes earlier RPS more expensive.)
#
# Siting / technology issues (prepare/test all with reference fuel prices):
# - no additional wind
# - no additional util-scale solar
# - no additional wind or util-scale solar
# - more DR + reserves from DR/EVs
# - no DR, BAU charging

# story:
# here's how well the RPS policy will do vs. a fossil baseline or vs. a least-cost plan
# (not clear which would be the real baseline); generally superior to fossil baseline,
# but could cost a bit vs. least-cost planning
# other questions: how much would LNG help? how important is DR? how much would a 2030 RPS cost?
# (for simplicity, we only benchmark these against the reference case with 100% by 2045)
# (maybe also look at whether switching to LNG would create regret in the 2030 RPS case)
# This answers immediate policy questions for HI, and also provides a template for answering
# these types of questions in other regions considering 100% RE.
# construction scenarios (tuples of scenario name and command-line arguments)
scenarios = (
    # base: EIA-based forecasts, mid-range hydrogen prices, NREL ATB reference technology prices,
    # PSIP pre-existing construction, various batteries (LS can provide shifting and reserves),
    # 10% DR, no LNG, optimal EV charging, full EV adoption
    [
        # standard settings with various price levels
        (
            '{}_oil_{}_tech_{}_{}'.format(oil_price, tech_price, target, plannning),
            '--inputs-dir inputs/{}_oil_{}_tech '.format(oil_price, tech_price)
            + (' --rps-deactivate' if policy == 'uncons' else '')
            + (' --ev-timing bau --demand-response-share 0.0' if target == 'existing' else '')
            + (
                ' --rps-targets 2020 0.4 2025 0.7 2030 1.0' if target == '2030'
                else (
                    '--rps-targets existing' if target == 'existing' else ''
                )
            )
            + (' --force-lng-tier none' if target in {'2030', '2045'} else '')
            + (' --rps-exact' if planning == 'exact' else '')
        )
        for oil_price in ['mid', 'low', 'high']
        for tech_price in ['mid', 'low', 'high']
         # note: currently ignoring 'uncons', because it confuses discussion and would
         # probably need to optimize EV adoption too
        for target in ['existing', '2045', '2030']  # , 'uncons']
        for planning in ['opt', 'exact']
        # only some for rerunning
        if target=='existing' or planning=='exact'
    ]
    unused = [
        # HECO PSIP plan (made with different assumptions and some errors, so omitted)
        # ('psip', '--psip-force --psip-relax-after 2025 --inputs-dir inputs/base'),

        # various LNG strategies with 2045 or 2030 RPS (all using reference fuel and tech prices)
        # Is it worth doing under 2045 policy? Would we regret it under 2030 policy?
        ('lng_2020_2045', '--force-lng-tier container_25 2020 2044 --inputs-dir inputs/mid_oil_mid_tech'),
        ('lng_2025_2045', '--force-lng-tier container_20 2025 2044 --inputs-dir inputs/mid_oil_mid_tech'),
        ('lng_2020_2030', '--force-lng-tier container_10 2020 2029 --rps-targets 2020 0.4 2025 0.7 2030 1.0 --inputs-dir inputs/mid_oil_mid_tech'),
        ('lng_2025_2030', '--force-lng-tier container_05 2025 2029 --rps-targets 2020 0.4 2025 0.7 2030 1.0 --inputs-dir inputs/mid_oil_mid_tech'),

        # siting/technology challenges (all using reference fuel and tech prices)
        # no more wind than is already in place
        ('no_new_wind', '--rps-no-new-wind --inputs-dir inputs/mid_oil_mid_tech'),
        # more demand response, plus reserves from DR and EVs
        (
            'dr_20',
            '--demand-response-share 0.2 --demand-response-reserve-types regulation contingency '
            '--ev-reserve-types regulation contingency --inputs-dir inputs/mid_oil_mid_tech'
        ),
        # no demand response, business-as-usual EV charging
        ('dr_0', '--demand-response-share 0.0 --ev-timing bau --inputs-dir inputs/mid_oil_mid_tech'),
        # # no DR, optimal EV charging
        # ('dr_0_opt_ev',  '--outputs-dir outputs/dr_0_opt_ev --logs-dir outputs/dr_0_opt_ev --demand-response-share 0.0 --inputs-dir inputs/mid_oil_mid_tech'),
        # # 10% DR, bau EV charging
        # ('dr_10_bau_ev', '--outputs-dir outputs/dr_10_bau_ev --logs-dir outputs/dr_10_bau_ev --ev-timing bau --inputs-dir inputs/mid_oil_mid_tech'),
        # three EV charging scenarios with LNG turned off, for consistency with main scenario, which doesn't pick LNG
        # no demand response, business-as-usual EV charging
        ('dr_0_ev_bau_no_lng', '--force-lng-tier none --demand-response-share 0.0 --ev-timing bau --inputs-dir inputs/mid_oil_mid_tech'),
        # no DR, optimal EV charging
        ('dr_0_ev_opt_no_lng',  '--force-lng-tier none --demand-response-share 0.0 --inputs-dir inputs/mid_oil_mid_tech'),
        # 10% DR, bau EV charging
        ('dr_10_ev_bau_no_lng', '--force-lng-tier none --ev-timing bau --inputs-dir inputs/mid_oil_mid_tech'),
    ]
)
# show range of cost for 2045 RPS, 2030 RPS or fossil, and show range of
# savings or costs for RPS vs. fossil in each economic environment

scenario_list = [
    '--scenario-name {0} --outputs-dir outputs/{0} --logs-dir outputs/{0} {1}'
    .format(*s).rstrip().replace('/', os.path.sep)
    for s in scenarios
]
scenario_args = dict(scenarios)

print "Writing scenarios.txt"
with open('scenarios.txt', 'w') as f:
    f.writelines(s + '\n' for s in scenario_list)

# build_tags = {  # build_scen: (abbrev, orig_inputs_dir)
#     'base': 'base_re',
#     'low_oil_prices': 'low_re',
#     'high_oil_prices': 'high_re',
#     'psip': 'psip',
#     'no_new_renewables': 'no_re',
#     'unconstrained': 'uncons',
#     '100_by_2030': '2030',
# }
#
# # replace tokens matching the template in string s
# def replace_token(s, template, old, new):
#     # add extra space, and require full matching including the space (full-token match)
#     s = ' ' + s + ' '
#     template = ' ' + template + ' '
#     result = s.replace(template.format(old), template.format(new))
#     return result[1:-1]
#
# scenario_cross = []
# for build_scen in build_tags.keys():
#     for eval_price in ('base', 'high_oil_prices', 'low_oil_prices'):
#         build_tag = build_tags[build_scen]
#         price_tag = eval_price.split('_')[0]  # base, high or low
#         eval_scen = build_tag + '_' + price_tag
#         if build_scen in {'low_oil_prices', 'high_oil_prices'}:
#             build_price = build_scen
#         else:
#             build_price = 'base'
#         scen = (
#             '--scenario-name {0} --outputs-dir outputs/{0} --logs-dir outputs/{0} {1}'
#             .format(eval_scen, scenario_args[build_scen])
#         )
#         # scen = replace_token(scen, 'outputs/{}', build_scen, eval_scen)
#         scen = replace_token(scen, 'inputs/{}', build_price, eval_price)
#         scen = scen + ' --include-module fix_build_vars --fix-build-vars-source-dir outputs/{}'.format(build_scen)
#         scenario_cross.append(scen)
# print "writing scenarios_cross.txt"
# with open('scenarios_cross.txt', 'w') as f:
#     f.writelines(s + '\n' for s in scenario_cross)


parser = argparse.ArgumentParser()
parser.add_argument('--skip-cf', action='store_true', default=False,
    help='Skip writing variable capacity factors file (for faster execution)')
parser.add_argument('--skip-ev-bids', action='store_true', default=False,
    help='Skip writing EV charging bids file (for faster execution)')
# default is daily slice samples for all but 4 days in 2007-08
parser.add_argument('--slice-count', type=int, default=727,
    help='Number of slices to generate for post-optimization evaluation.')
parser.add_argument('--tiny-only', action='store_true', default=False,
    help='Only prepare inputs for the tiny scenario for testing.')

cmd_line_args = parser.parse_args()

# settings used for the base scenario, will be adapted for others
# (these will be passed as arguments when the queries are run)
args = dict(
    # directory to store data in
    inputs_dir='inputs',
    # skip writing capacity factors file if specified (for speed)
    skip_cf = cmd_line_args.skip_cf,
    skip_ev_bids = cmd_line_args.skip_ev_bids,
    # use heat rate curves for all thermal plants
    use_incremental_heat_rates=True,
    # could be 'tiny', 'rps', 'rps_mini' or possibly '2007', '2016test', 'rps_test_45', or 'main'
    # '2020_2025' is two 5-year periods, with 24 days per period, starting in 2020 and 2025
    # "2020_2045_23_2_2" is 5 5-year periods, 6 days per period before 2045, 12 days per period in 2045, 12 h/day
    # time_sample = "2020_2045_23_2_2", # 6 mo/year before 2045
    # time_sample = "k_means_5_12_2",  # representative days, 5-year periods, 12 sample days per period, 2-hour spacing
    # time_sample = "k_means_5_24",  # representative days, 5-year periods, 12 sample days per period, 1-hour spacing
    time_sample="k_means_5_24_2",  # representative days, 5-year periods, 12 sample days per period, 2-hour spacing
    # subset of load zones to model
    load_zones = ('Oahu',),
    # "hist"=pseudo-historical, "med"="Moved by Passion", "flat"=2015 levels, "PSIP_2016_04"=PSIP 4/16
    load_scen_id = "PSIP_2016_12", # matches PSIP report but not PSIP modeling, not well documented but seems reasonable
    # in early years and flatter in later years, with no clear justification for that trend.
    # "PSIP_2016_12"=PSIP 12/16; ATB_2018_low, ATB_2018_mid, ATB_2018_high = NREL ATB data; ATB_2018_flat=unchanged after 2018
    tech_scen_id='ATB_2018_mid',
    # tech_scen_id='PSIP_2016_12',
    # '1'=low, '2'=high, '3'=reference, 'EIA_ref'=EIA-derived reference level, 'hedged'=2020-2030 prices from Hawaii Gas
    fuel_scen_id='AEO_2018_Reference',
    # note: 'unhedged_2016_11_22' is basically the same as 'PSIP_2016_09', but derived directly from EIA and includes various LNG options
    # Blazing a Bold Frontier, Stuck in the Middle, No Burning Desire, Full Adoption,
    # Business as Usual, (omitted or None=none)
    # ev_scenario = 'PSIP 2016-12',  # PSIP scenario
    ev_scenario = 'Full Adoption',   # 100% by 2045, to match Mayors' commitments
    # should the must_run flag be converted to set minimum commitment for existing plants?
    enable_must_run = 0,
    # list of technologies to exclude (currently CentralFixedPV, because we don't have the logic
    # in place yet to choose between CentralFixedPV and CentralTrackingPV at each site)
    # Lake_Wilson is excluded because we don't have the custom code yet to prevent
    # zero-crossing reserve provision
    exclude_technologies = ('CentralFixedPV','Lake_Wilson'),
    base_financial_year = 2018,
    interest_rate = 0.06,
    discount_rate = 0.03,
    # used to convert nominal costs in the tables to real costs
    inflation_rate = 0.025,
    # maximum type of reserves that can be provided by each technology (if restricted);
    # should be a list of tuples of (technology, reserve_type); if not specified, we assume
    # each technology can provide all types of reserves; reserve_type should be "none",
    # "contingency" or "reserve"
    max_reserve_capability=[('Battery_Conting', 'contingency')],
)

# electrolyzer data from centralized current electrolyzer scenario version 3.1 in
# http://www.hydrogen.energy.gov/h2a_prod_studies.html ->
# "Current Central Hydrogen Production from PEM Electrolysis version 3.101.xlsm"
# and
# "Future Central Hydrogen Production from PEM Electrolysis version 3.101.xlsm" (2025)
# (cited by 46719.pdf)
# note: we neglect land costs because they are small and can be recovered later
# TODO: move electrolyzer refurbishment costs from fixed to variable

# liquifier and tank data from http://www.nrel.gov/docs/fy99osti/25106.pdf

# fuel cell data from http://www.nrel.gov/docs/fy10osti/46719.pdf

# note: the article below shows 44% efficiency converting electricity to liquid
# fuels, then 30% efficiency converting to traction (would be similar for electricity),
# so power -> liquid fuel -> power would probably be less efficient than
# power -> hydrogen -> power. On the other hand, it would avoid the fuel cell
# investments and/or could be used to make fuel for air/sea freight, so may be
# worth considering eventually. (solar at $1/W with 28% cf would cost
# https://www.greencarreports.com/news/1113175_electric-cars-win-on-energy-efficiency-vs-hydrogen-gasoline-diesel-analysis
# https://twitter.com/lithiumpowerlpi/status/911003718891454464

inflate_1995 = (1.0+args["inflation_rate"])**(args["base_financial_year"]-1995)
inflate_2007 = (1.0+args["inflation_rate"])**(args["base_financial_year"]-2007)
inflate_2008 = (1.0+args["inflation_rate"])**(args["base_financial_year"]-2008)
h2_lhv_mj_per_kg = 120.21   # from http://hydrogen.pnl.gov/tools/lower-and-higher-heating-values-fuels
h2_mwh_per_kg = h2_lhv_mj_per_kg / 3600     # (3600 MJ/MWh)

current_electrolyzer_kg_per_mwh=1000.0/54.3    # (1000 kWh/1 MWh)(1kg/54.3 kWh)   # TMP_Usage
current_electrolyzer_mw = 50000.0 * (1.0/current_electrolyzer_kg_per_mwh) * (1.0/24.0)   # (kg/day) * (MWh/kg) * (day/h)    # design_cap cell
future_electrolyzer_kg_per_mwh=1000.0/50.2    # TMP_Usage cell
future_electrolyzer_mw = 50000.0 * (1.0/future_electrolyzer_kg_per_mwh) * (1.0/24.0)   # (kg/day) * (MWh/kg) * (day/h)    # design_cap cell

current_hydrogen_args = dict(
    hydrogen_electrolyzer_capital_cost_per_mw=144641663*inflate_2007/current_electrolyzer_mw,        # depr_cap cell
    hydrogen_electrolyzer_fixed_cost_per_mw_year=7134560.0*inflate_2007/current_electrolyzer_mw,         # fixed cell
    hydrogen_electrolyzer_variable_cost_per_kg=0.0,       # they only count electricity as variable cost
    hydrogen_electrolyzer_kg_per_mwh=current_electrolyzer_kg_per_mwh,
    hydrogen_electrolyzer_life_years=40,                      # plant_life cell

    hydrogen_fuel_cell_capital_cost_per_mw=813000*inflate_2008,   # 46719.pdf
    hydrogen_fuel_cell_fixed_cost_per_mw_year=27000*inflate_2008,   # 46719.pdf
    hydrogen_fuel_cell_variable_cost_per_mwh=0.0, # not listed in 46719.pdf; we should estimate a wear-and-tear factor
    hydrogen_fuel_cell_mwh_per_kg=0.53*h2_mwh_per_kg,   # efficiency from 46719.pdf
    hydrogen_fuel_cell_life_years=15,   # 46719.pdf

    hydrogen_liquifier_capital_cost_per_kg_per_hour=inflate_1995*25600,       # 25106.pdf p. 18, for 1500 kg/h plant, approx. 100 MW
    hydrogen_liquifier_fixed_cost_per_kg_hour_year=0.0,   # unknown, assumed low
    hydrogen_liquifier_variable_cost_per_kg=0.0,      # 25106.pdf p. 23 counts tank, equipment and electricity, but those are covered elsewhere
    hydrogen_liquifier_mwh_per_kg=10.0/1000.0,        # middle of 8-12 range from 25106.pdf p. 23
    hydrogen_liquifier_life_years=30,             # unknown, assumed long

    liquid_hydrogen_tank_capital_cost_per_kg=inflate_1995*18,         # 25106.pdf p. 20, for 300000 kg vessel
    liquid_hydrogen_tank_minimum_size_kg=300000,                       # corresponds to price above; cost/kg might be 800/volume^0.3
    liquid_hydrogen_tank_life_years=40,                       # unknown, assumed long
)

# future hydrogen costs
future_hydrogen_args = current_hydrogen_args.copy()
future_hydrogen_args.update(
    hydrogen_electrolyzer_capital_cost_per_mw=58369966*inflate_2007/future_electrolyzer_mw,        # depr_cap cell
    hydrogen_electrolyzer_fixed_cost_per_mw_year=3560447*inflate_2007/future_electrolyzer_mw,         # fixed cell
    hydrogen_electrolyzer_variable_cost_per_kg=0.0,       # they only count electricity as variable cost
    hydrogen_electrolyzer_kg_per_mwh=future_electrolyzer_kg_per_mwh,
    hydrogen_electrolyzer_life_years=40,                      # plant_life cell

    # table 5, p. 13 of 46719.pdf, low-cost
    # ('The value of $434/kW for the low-cost case is consistent with projected values for stationary fuel cells')
    hydrogen_fuel_cell_capital_cost_per_mw=434000*inflate_2008,
    hydrogen_fuel_cell_fixed_cost_per_mw_year=20000*inflate_2008,
    hydrogen_fuel_cell_variable_cost_per_mwh=0.0, # not listed in 46719.pdf; we should estimate a wear-and-tear factor
    hydrogen_fuel_cell_mwh_per_kg=0.58*h2_mwh_per_kg,
    hydrogen_fuel_cell_life_years=26,
)

mid_hydrogen_args = {
    key: 0.5 * (current_hydrogen_args[key] + future_hydrogen_args[key])
    for key in future_hydrogen_args.keys()
}
args.update(future_hydrogen_args)

args.update(
    pumped_hydro_headers=[
        'ph_project_id', 'ph_load_zone', 'ph_capital_cost_per_mw',
        'ph_project_life', 'ph_fixed_om_percent',
        'ph_efficiency', 'ph_inflow_mw', 'ph_max_capacity_mw'],
    pumped_hydro_projects=[
        ['Lake_Wilson', 'Oahu', 2800*1000+35e6/150, 50, 0.015, 0.77, 10, 150],
    ]
)

# TODO: move this into the data import system
args.update(
    rps_targets = {2015: 0.15, 2020: 0.30, 2030: 0.40, 2040: 0.70, 2045: 1.00}
)
rps_2030 = {2020: 0.4, 2025: 0.7, 2030: 1.0}

# # dummy scenario data for base model
# pha_scenario_count = 4 # 120
# pha_scenario_digit_count = 3
# args['pha_scenario_count'] = pha_scenario_count
# args['pha_scenario_digit_count'] = pha_scenario_digit_count;
# args['pha_current_scenario'] = 0;

# write data for all construction models
alt_args = [
    # only 2 days, useful for testing and debugging
    dict(inputs_subdir='tiny', time_sample='tiny'),
] + [
    # scenarios for various oil and tech prices
    dict(
        inputs_subdir='{}_oil_{}_tech'.format(oil_price, tech_price),
        fuel_scen_id='AEO_2018_{}'.format(
            {'low': 'Low_Oil_Prices', 'mid': 'Reference', 'high': 'High_Oil_Prices'}
            [oil_price]
        ),
        tech_scen_id='ATB_2018_{}'.format(tech_price)
    )
    for oil_price in ['mid', 'low', 'high']
    for tech_price in ['mid', 'low', 'high']
]
# choose the right hydrogen args based on the last part of the tech_scen_id
for a in alt_args:
    level = a.get('tech_scen_id', args.get('tech_scen_id', 'mid')).split('_')[-1]
    hydrogen_args = {
        'low': future_hydrogen_args,
        'high': current_hydrogen_args
    }.get(level, mid_hydrogen_args)
    a.update(hydrogen_args)

if cmd_line_args.tiny_only:
    # skip all except the tiny inputs directory
    alt_args = [d for d in alt_args if d.get('time_sample', args.get('time_sample', ''))=='tiny']

for a in alt_args:
    # clone the arguments dictionary and update it with settings from the alt_args entry, if any
    active_args = dict(args.items() + a.items())
    scenario_data.write_tables(**active_args)

# write data for all time-slice models based on the construction models
n_slices = cmd_line_args.slice_count
scen_ids = range(n_slices)
n_digits = 3
for a in alt_args:
    for i in scen_ids:
        tag = str(i).zfill(n_digits)
        slice_args = dict(
            time_sample='slice_5_1_'+tag,
            inputs_subdir=os.path.join(a.get('inputs_subdir', ''), 'slices', tag)
        )
        active_args = dict(args.items() + a.items() + slice_args.items())
        scenario_data.write_tables(**active_args)
