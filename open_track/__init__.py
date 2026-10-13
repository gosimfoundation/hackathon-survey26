"""Open track for the new AOH tasks: a trusted engine and an executor on separate machines.

engine.py    trusted side: hidden bundle (salt + hidden wording pools), environment, official replay score.
executor.py  participant side: the agent in a network-less container beside a metered model proxy.
They exchange only public protocol messages through the database (migration 20261013000000_open_track).
"""
