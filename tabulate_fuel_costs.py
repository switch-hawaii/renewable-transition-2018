import os
from collections import defaultdict

n_digits = 4    # number of digits used in filenames
n_scenarios = 125
inputs_dir = "inputs_tiny"
inputs_subdir = "pha_125_logistic"
pha_dir = os.path.join(inputs_dir, inputs_subdir)
mean_dir = os.path.join(inputs_dir, inputs_subdir + "_mean") 

# get weights for each scenario
with open(os.path.join(pha_dir, 'scenario_weights.tsv')) as f:
    strs = [r.split("\t") for r in f.read().strip().split('\n')[1:]]
    weight = {int(scen): float(wgt) for scen, wgt in strs}

values = defaultdict(list)
sums = defaultdict(float)

for scen in range(n_scenarios):
    with open(os.path.join(
            inputs_dir, inputs_subdir, "fuel_supply_curves_{}.dat".format(str(scen).zfill(n_digits))
        )
    ) as f:
        rows = [r.split("\t") for r in f.read().split('\n')]
        for r in rows[1:-2]:   # omit header row and semicolon and blank line at end
            key = r[0]
            if r[2] != "base":
                key += r[2]
            values[(key, r[1])].append(r[3])
            sums[(r[0], r[1], r[2])] += float(r[3]) * weight[scen]

# store the average values back into the row list
for r in rows[1:-2]:
    r[3] = str(sums[(r[0], r[1], r[2])] / sum(weight[scen] for scen in weight))

# write the mean values to a special fuel supply curve
if not os.path.exists(mean_dir):
    os.makedirs(mean_dir)
with open(os.path.join(mean_dir, "fuel_supply_curves_0000.dat"), "w") as f:
    f.write("\n".join(["\t".join(r) for r in rows]))

with open(os.path.join(pha_dir, "fuel_supply_costs.tsv"), "w") as f:
    f.write("fuel\tyear\tprice_per_mmbtu\n")
    f.writelines(
        "\t".join(list(k) + map(str, values[k])) + "\n"
            for k in sorted(values.keys())
    )

