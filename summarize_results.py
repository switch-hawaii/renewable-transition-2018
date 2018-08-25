# %% setup
from __future__ import print_function
from __future__ import division

import matplotlib as mpl
# give preference to Arial (instead of Vera Sans, which is bigger)
# note: the font list has to be changed before matplotlib.pyplot is loaded for some reason
# see https://matplotlib.org/examples/api/font_family_rc.html for an example
if u'Arial' in mpl.rcParams['font.sans-serif']:
    mpl.rcParams['font.sans-serif'].remove(u'Arial')
    mpl.rcParams['font.sans-serif'].insert(0, u'Arial')
# %matplotlib inline

import os, math, itertools
import pandas as pd
import matplotlib.pyplot as plt

# %% hourly costs
costs = dict()
oils = ['low', 'mid', 'high']
techs = ['low', 'mid', 'high']
policies = ['bau', '2045', '2030']
for oil in oils:
    for tech in techs:
        for policy in policies:
            with open(os.path.join(
                'outputs',
                '{}_oil_{}_tech_{}'.format(oil, tech, policy.replace('bau', 'bau_01')),
                'total_cost.txt'
            )) as f:
                val_str = f.readlines()[-1].strip().replace('?', '')
                costs[(oil, tech, policy)] = float(val_str)
        diff_2030 = costs[oil, tech, '2030'] - costs[oil, tech, 'bau']
        diff_2045 = costs[oil, tech, '2045'] - costs[oil, tech, 'bau']
        print(",".join(itertools.chain(
            [oil, tech],
            (str(costs[oil, tech, p]) for p in policies)
        )))
        # print(
        #     "{}, {}: {:+,}, {:+,}"
        #     .format(
        #         oil, tech, math.trunc(diff_2045), math.trunc(diff_2030)
        #     )
        # )

def cost_tables():

    # # %% make table
    # df = pd.Series(costs).reset_index()
    # df.columns = ['oil', 'tech', 'policy', 'cost']
    # def delta_str(x):
    #     val = (x-min(x))/min(x)
    #     res = val.map('(+{:.0%})'.format)
    #     res[val == 0] = ''
    #     return res
    #
    # def delta_b_str(x):
    #     val = ((x-min(x))/1e9).round(1)  # difference from min, in $B
    #     res = val.map('(+{})'.format)
    #     res[val == 0] = ''
    #     return res
    #
    # def one_str(x):
    #     dif = x-x.min()
    #     dif_str = (dif/1e9).round(1).map(' {:+}'.format)
    #     dif_str[dif==0] = ''
    #     val_str = (x/1e9).round(1).map('{}'.format)
    #     val_str[dif!=0] = dif_str[dif!=0]
    #     # result_str = (x/1e9).round(1).map('{}'.format) + dif_str
    #     print(val_str)
    #     return val_str
    #
    # def vs_fossil(x):
    #     dif = x-x.iloc[2]
    #     dif_str = (dif/1e9).astype(float).round(1).map('{:+}'.format)
    #     dif_str[dif==0] = ''
    #     val_str = (x/1e9).astype(float).round(1).map('{}'.format)
    #     val_str[dif!=0] = dif_str[dif!=0]
    #     # result_str = (x/1e9).round(1).map('{}'.format) + dif_str
    #     # print(val_str)
    #     return val_str
    #
    # %% cost difference table
    cost_dif = {
        (oil, tech, policy):
        '{:+2.1%}'.format((costs[oil, tech, policy]/costs[oil, tech, 'bau']-1))
        # '{:+2.1f}'.format((costs[oil, tech, policy]-costs[oil, tech, 'bau'])/1e9)
        for oil in oils
        for tech in techs
        for policy in policies if policy != 'bau'
    }

    df = pd.Series(cost_dif).reset_index()
    df.columns = ['oil', 'tech', 'policy', 'cost_diff']
    df['oil'] = pd.Categorical(df['oil'], oils)
    df['tech'] = pd.Categorical(df['tech'], techs)
    df['policy'] = pd.Categorical(df['policy'], policies)
    df = df.set_index(['oil', 'tech', 'policy']).unstack(['policy', 'oil']).sort_index(axis=1)
    df

    # %% total cost table ($B)
    totals = pd.Series(costs).reset_index()
    totals.columns = ['oil', 'tech', 'policy', 'cost']
    totals['oil'] =  pd.Categorical(totals['oil'], oils, ordered=True)
    totals['tech'] = pd.Categorical(totals['tech'], techs, ordered=True)
    totals['policy'] = pd.Categorical(totals['policy'], policies, ordered=True)
    totals['cost'] = (totals['cost']/1e9).map('{:3.1f}'.format)
    total_table = totals.set_index(['oil', 'tech', 'policy']).unstack('oil')
    total_table

# %%
def cost_plot():
# %% cost plot
    cost_plot = pd.Series(costs).reset_index()
    cost_plot.columns = ['oil', 'tech', 'policy', 'cost']
    cost_plot['oil'] =  pd.Categorical(cost_plot['oil'], oils, ordered=True)
    cost_plot['tech'] = pd.Categorical(cost_plot['tech'], techs, ordered=True)
    cost_plot['policy'] = pd.Categorical(cost_plot['policy'], policies, ordered=True)
    cost_plot['cost'] /= 1e9

    cost_plot = cost_plot.set_index(['oil', 'tech', 'policy']).unstack('policy')
    colors = {'low': 'green', 'mid': 'orange', 'high': 'red'}
    markers = {'low': '1', 'mid': '4', 'high': '2'} # triangles pointing various ways
    policy_names = {'bau': 'business-as-usual', '2045': '100% by 2045', '2030': '100% by 2030'}
    x = [policy_names[p] for p in cost_plot.columns.levels[1]]
    fig = plt.figure(figsize=(5, 3)) # a little big because matplotlib seems to oversize fonts by ~10%
    ax = fig.add_axes([0.13, 0.15, 0.7, 0.82])
    for oil in oils:
        for tech in techs:
            y = cost_plot.loc[(oil, tech), :].values
            ax.plot(x, y, color=colors[tech]) # , linecolor=colors[tech], marker=markers[oil], markercolor=colors[oil])

    ax.set_ylim(0, 65)
    ax.set_xlim(-.3, 2.3)
    # ax.set_xlim(0, 2.9)
    ax.patch.set_alpha(0.0)  # doesn't seem to work
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)
    for oil in oils:
        ax.annotate(
            '{} oil prices'.format(oil),
            xy=(0.0, cost_plot.loc[(oil, 'high'), ('cost', 'bau')] + 1)
        )
    # ax.annotate('mid oil prices', xy=(0.0, 38))
    # ax.annotate('low oil prices', xy=(0.0, 21))
    y_base = cost_plot.loc[('high', 'mid'), ('cost', '2030')]-0.5
    for tech in techs:
        x = 2.1
        y = y_base + {'low': -1, 'mid': 0, 'high': 1}[tech] * 3.5
        ax.annotate(tech+' tech prices', xy=(x, y), color=colors[tech])

    ax.set_ylabel('NPV of electricity and transport cost \n(billion 2018$)', fontweight='bold')
    ax.set_xlabel('policy', fontweight='bold')
    fig.savefig('all scenario costs.pdf')


# %%
def rps_plot():
# %%
    rows = []
    for oil in oils:
        for tech in techs:
            for policy in policies:
                scen = '{}_oil_{}_tech_{}'.format(oil, tech, policy.replace('bau', 'bau_01'))
                file = 'outputs/{scen}/summary_{scen}.tsv'.format(scen=scen)
                if os.path.exists(file):
                    df = pd.read_csv(file, sep='\t')
                else:
                    df = pd.DataFrame({'scenario': scen}, index=[0])
                df['scenario'] = '{}_oil_{}_tech_{}'.format(oil, tech, policy)
                rows.append(df)
    pd.concat(rows, axis=0)
    # re_share = df.loc[:, 'renewable_share_2020':'renewable_share_2045']
