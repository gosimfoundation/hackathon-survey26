# osc_run_v3: contestant kit

Everything here is public. Read PROBLEM.md first.

Run an agent locally on dev seed N (0-9):

    python3 -m aohkit.runner --problem osc_run_v3 --seed N --agent 'python3 agent.py'

Compare with the trivial baseline:

    python3 -m aohkit.runner --problem osc_run_v3 --seed N --agent 'python3 osc_run_v3/baseline_trivial.py'

Rules: write agent.py in this directory using aohkit.agent_base.serve; standard library only; do not import or
instantiate the environment inside agent.py. aohkit.llm.ask is optional and metered (costs points).
Official scoring uses hidden seeds and hidden text that are not in this kit.
