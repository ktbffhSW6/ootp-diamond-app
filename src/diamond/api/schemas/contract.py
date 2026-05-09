"""Player contract Pydantic schemas — backs the player-page Contract section.

Backed by the L1 view ``contract_current`` (latest dump per player).
OOTP carries the deal as a flat row with `salary0..salary14` (15-year
ceiling) plus option flags + buyout amounts + no-trade + bonus
incentives.

Contract semantics decoded from data probes:

- ``season_year`` is the contract's start year. ``salary0`` is that
  year's pay; ``salary1`` is year 2; etc. Salaries beyond the deal
  length are stored as 0.
- ``years`` is the contract length (number of populated salary slots).
- ``current_year`` is 1-based: 1 = first year of the deal, 2 = second.
  We surface as 0-based ``current_year_index`` to match Python list
  semantics.
- ``last_year_team_option`` (and player / vesting) flags whether the
  FINAL year of the deal is that option type. ``next_last_year_*``
  flags the SECOND-TO-LAST year. Both can co-exist (rare): a 5-year
  deal where year 4 is a player option and year 5 is a team option.
- ``opt_out`` is a year offset (1-based, like current_year) where the
  player can void the rest of the deal. 0 = no opt-out clause.
- ``no_trade`` is a boolean flag.
- Bonus columns (``minimum_pa``, ``mvp_bonus``, etc.) are skipped in
  v1 — rarely material for the GM-decision view; can land later.

The route assembles a ``PlayerContract`` with one ``ContractYear`` row
per populated salary slot, with option flags resolved + the current
year highlighted. Players with no active contract (released / FA /
amateur) have ``contract = None``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractYear(BaseModel):
    """One year of a multi-year deal.

    ``year`` is the actual season; ``season_index`` is 0-based offset
    from contract start (useful for the UI's bar-chart x-axis).
    Option flags are mutually exclusive across the three types but
    co-exist with ``has_buyout`` when the option is bought out
    instead of exercised.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    season_index: int
    salary: int  # USD
    is_current: bool
    is_team_option: bool
    is_player_option: bool
    is_vesting_option: bool
    has_buyout: bool
    buyout_amount: int  # 0 when no buyout
    can_opt_out: bool  # the season at which opt_out fires (rare flag)


class PlayerContract(BaseModel):
    """The active contract for a player.

    Aggregate fields (``total_value``, ``remaining_value``) are
    server-computed sums so the UI doesn't have to sum across the
    rows array. Both are in raw USD.

    ``contract_team_abbr`` is the team that's actually paying the
    salary (the team that signed the deal); usually equals the
    player's current team but can differ after a trade with retained
    salary — captured in the ``retained`` flag.
    """

    model_config = ConfigDict(frozen=True)

    contract_team_id: int | None
    contract_team_abbr: str | None
    start_year: int
    years: int
    current_year_index: int  # 0-based; -1 if contract hasn't started
    no_trade: bool
    retained_by_prior_team: bool
    total_value: int
    remaining_value: int  # current year onward
    rows: list[ContractYear]
