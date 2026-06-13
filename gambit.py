"""Gambit viability projection.

A gambit: liberating the enemy-held ATTACKING planet before the DEFENDING planet's defense
timer expires instantly defends the defender too. The question this answers is the one the
community keeps getting wrong: *is the gambit still winnable, and if not, how many more
Helldivers would it take?*

Model (decided with the user, 2026-06-12): don't assume a population — SOLVE for the divers
needed. From the two-snapshot flow we observe the attacker's gross player-damage rate (HP/sec
before regen). Per-diver throughput = that / current attacker players. Then the divers required
to clear the attacker's remaining HP by the defense deadline (regen is a flat subtraction, so
more divers help super-linearly):

    players_needed    = (atk_remaining_hp / defense_time_left + atk_regen_per_sec) / per_diver
    additional_needed = players_needed - atk_players

The realistic mobilizable pool is the DEFENDING planet's divers (switching them to the attacker
is exactly what wins the defense), so the gambit is WINNABLE iff additional_needed <= def_players.
If not, the shortfall beyond even full mobilization is additional_needed - def_players.

`players_needed` is always finite (gross scales with players, regen is fixed), so there is never
a "not viable" dead end — we can always state a concrete "needs X more".
"""


def attacker_gross_rate(health1, health2, regen_per_sec, window_seconds):
    """Observed gross player-damage rate (HP/sec, before regen) on an enemy-held liberation
    planet over the snapshot window. = regen + net liberation progress per second. Returns None
    if it can't be measured (no window, or players doing < 0 effective damage). Never negative."""
    if not window_seconds or window_seconds <= 0:
        return None
    # Enemy HP falls as the planet is liberated; regen pushes it back up. Player damage rate =
    # regen rate + the rate HP actually fell.
    gross = regen_per_sec + (health1 - health2) / window_seconds
    return gross if gross > 0 else None


def gambit_viability(*, atk_remaining_hp, atk_gross_rate, atk_players, atk_regen_per_sec,
                     def_players, defense_time_left_sec):
    """Project gambit viability. atk_gross_rate = observed gross player-damage rate (HP/sec)
    on the attacker (see attacker_gross_rate). Returns a dict:
      {status: "ok"|"insufficient_data"|"window_closed", winnable, players_needed,
       additional_needed, shortfall}
    """
    if atk_players is None or atk_players <= 0 or not atk_gross_rate or atk_gross_rate <= 0 \
            or atk_remaining_hp is None or atk_remaining_hp <= 0:
        return {"status": "insufficient_data"}
    if defense_time_left_sec is None or defense_time_left_sec <= 0:
        return {"status": "window_closed"}

    per_diver = atk_gross_rate / atk_players
    needed_net_rate = atk_remaining_hp / defense_time_left_sec      # HP/sec required to finish in time
    players_needed = (needed_net_rate + (atk_regen_per_sec or 0)) / per_diver
    additional_needed = players_needed - atk_players
    return {
        "status": "ok",
        # WINNABLE = the attacker's CURRENT divers are enough to liberate it before the deadline.
        "winnable": additional_needed <= 0,
        "players_needed": players_needed,
        "additional_needed": max(0.0, additional_needed),   # more divers needed on the attacker to win
        # secondary realism hint: could moving the defending planet's divers cover that deficit?
        "mobilizable": additional_needed <= (def_players or 0),
    }


def project_gambit(defender, attacker, atk_health1, window_seconds, defense_time_left_sec):
    """Full projection for one gambit pair from the two-snapshot data. `defender`/`attacker`
    are built planet dicts; `atk_health1` is the attacker's snapshot-1 contested health.
    Returns {defense_time_left_sec, attacker_lib_hours, viability:{...}}."""
    gross = (attacker_gross_rate(atk_health1, attacker.get("contest_health"),
                                 attacker.get("regen_per_second") or 0, window_seconds)
             if atk_health1 is not None else None)
    viability = gambit_viability(
        atk_remaining_hp=attacker.get("contest_health"),
        atk_gross_rate=gross,
        atk_players=attacker.get("player_count"),
        atk_regen_per_sec=attacker.get("regen_per_second") or 0,
        def_players=defender.get("player_count"),
        defense_time_left_sec=defense_time_left_sec,
    )
    return {
        "defense_time_left_sec": defense_time_left_sec,
        "attacker_lib_hours": attacker.get("liberation_time_hours"),
        "viability": viability,
    }
