import pandas as pd;
f = [(name.split('/')[-2], float(val.strip('?'))) for name, val in [r.strip().split(':') for r in open('cost_summary.txt').readlines()]]
df = pd.DataFrame.from_records(f, columns=['scenario', 'cost']).set_index('scenario').sort_index()
print df
