"""Git d'un projet côté pont (phase 14 au web) : état, journal, diff, indexation, commit,
fetch / pull / push, par `git_repo` ; chemins limités par `bridge_data.safe_path`. Rempli par le
lot « pages »."""


class GitApi:
    def __init__(self, bridge):
        self.bridge = bridge
        bridge.add_handlers({})
