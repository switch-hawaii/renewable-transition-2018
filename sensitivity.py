
# specify ev_scen_ids in args, and scenario_data will create multiple
# .tab files to match, each called ev_share.scen_id.tab

def load_inputs(m, switch_data, inputs_dir):
    """
    Import data from alternative .tab files if requested.
    """
    if m.options.ev_share_tab
    switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'ev_share.tab'),
        auto_select=True,
        param=m.ev_share
    )

# --input-aliases ev_share.tab=ev_share.flat.tab rps=rps.2030.tab
