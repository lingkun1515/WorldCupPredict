"""Statistical prediction models — Poisson, Elo, ensemble methods."""
import json, math, os
from config import DATA_DIR


def poisson_prob(lmbda, k):
    """Probability of k goals given expected goals lambda."""
    return math.exp(-lmbda) * (lmbda ** k) / math.factorial(k)


def _load_team_ratings():
    path = os.path.join(DATA_DIR, "team_ratings.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}
    return {}


def poisson_prediction(home_team, away_team, home_advantage=0.10):
    """
    Poisson model prediction.

    Expected goals = team_attack_strength × opponent_defense_weakness × home_advantage

    Returns: dict with predicted score, confidence, full score distribution
    """
    ratings = _load_team_ratings()

    # Base rating: 70 (out of ~100). Convert to expected goals scale (~1.4 goals avg)
    home_r = ratings.get(home_team, 70)
    away_r = ratings.get(away_team, 70)

    # Expected goals: higher rating = more goals, adjusted by opponent
    # League average goals: ~1.4 per team. Scale ratings to this baseline.
    league_avg = 1.35
    # Dynamic home advantage: varies by rating gap (reduced for neutral-venue knockout)
    ha_factor = home_advantage * (1 + abs(home_r - away_r) / 200)
    home_lambda = league_avg * (home_r / 70) * (1 + (home_r - away_r) / 140) * (1 + ha_factor)
    away_lambda = league_avg * (away_r / 70) * (1 + (away_r - home_r) / 140) * (1 - ha_factor * 0.5)
    # Symmetric strong-team bonus — neutral venue, no home bias
    if home_r > 85 and away_r < 75:
        home_lambda += 0.15
    if away_r > 85 and home_r < 75:
        away_lambda += 0.15
    if abs(home_r - away_r) < 10:
        home_lambda *= 0.9; away_lambda *= 0.9  # Close match = fewer goals
    
    # Add noise scaled by rating gap — close matches get less noise
    import random as _prng
    _noise_rng = _prng.Random(hash(home_team + away_team + "poisson") % 2**31)
    gap = abs(home_r - away_r)
    noise_scale = max(0.12, min(0.45, 0.12 + gap * 0.008))  # 0.12 for close, up to 0.45 for huge gaps
    home_lambda = max(0.2, min(5.0, home_lambda))
    away_lambda = max(0.1, min(5.0, away_lambda))

    # Generate score probabilities (0-6 goals each)
    # Knockout matches: reduce draw probability by 30%
    score_dist = []
    for h in range(0, 7):
        for a in range(0, 7):
            prob = poisson_prob(home_lambda, h) * poisson_prob(away_lambda, a) * 100
            if h == a and h > 0:
                prob *= 0.55  # Penalize draws in knockout
            if prob > 0.3:
                score_dist.append({"home": h, "away": a, "prob": round(prob, 1)})
    if not score_dist:
        score_dist = [{"home": 1, "away": 0, "prob": 30.0}, {"home": 0, "away": 1, "prob": 20.0}]
    score_dist.sort(key=lambda x: -x["prob"])
    score_dist = score_dist[:8]
    
    # Most likely score
    best = score_dist[0]
    confidence = min(0.85, score_dist[0]["prob"] / 30 + 0.3)
    
    # Compute outcome probabilities
    home_win_prob = sum(d["prob"] for d in score_dist if d["home"] > d["away"])
    draw_prob = sum(d["prob"] for d in score_dist if d["home"] == d["away"])
    away_win_prob = sum(d["prob"] for d in score_dist if d["home"] < d["away"])
    total = home_win_prob + draw_prob + away_win_prob
    
    return {
        "home_team": home_team,
        "away_team": away_team,
        "model": "Poisson",
        "predicted_home_goals": best["home"],
        "predicted_away_goals": best["away"],
        "confidence": round(confidence, 2),
        "home_lambda": round(home_lambda, 2),
        "away_lambda": round(away_lambda, 2),
        "market_home_prob": min(0.85, max(0.05, round(home_win_prob / total, 3) if total > 0 else 0.40)),
        "market_draw_prob": max(0.05, round(draw_prob / total, 3) if total > 0 else 0.25),
        "market_away_prob": max(0.05, round(away_win_prob / total, 3) if total > 0 else 0.35),
        "score_distribution": score_dist[:5],
        "odds_sources_used": len(ratings),
        "reasoning": [
            f"泊松模型: {home_team} 预期进球 {home_lambda:.2f} (评级{home_r})",
            f"{away_team} 预期进球 {away_lambda:.2f} (评级{away_r})",
            f"最可能比分 {best['home']}-{best['away']} (概率 {best['prob']:.1f}%)",
            f"主胜概率 {home_win_prob/total*100:.0f}%, 平局 {draw_prob/total*100:.0f}%, 客胜 {away_win_prob/total*100:.0f}%",
        ],
        "confidence_basis": f"泊松分布模型 (λ_h={home_lambda:.2f}, λ_a={away_lambda:.2f})",
        "x_factor": f"若{away_team}防守超预期，进球数可能低于{away_lambda:.1f}",
    }


def ensemble_prediction(llm_pred, stat_pred, llm_weight=0.6):
    """
    Ensemble: blend LLM and statistical predictions with proper sampling.
    
    Merges score distributions and samples from the combined distribution
    rather than just averaging predicted scores — ensuring outcome diversity.
    """
    # Merge score distributions — penalize draws for knockout context
    dist_map = {}
    for d in llm_pred.get("score_distribution", []):
        key = f"{d['home']}-{d['away']}"
        val = d["prob"] * llm_weight
        h, a = int(key.split("-")[0]), int(key.split("-")[1])
        if h == a and h > 0:
            val *= 0.15  # Strong draw penalty for knockout
        dist_map[key] = dist_map.get(key, 0) + val
    for d in stat_pred.get("score_distribution", []):
        key = f"{d['home']}-{d['away']}"
        val = d["prob"] * (1 - llm_weight)
        h, a = int(key.split("-")[0]), int(key.split("-")[1])
        if h == a and h > 0:
            val *= 0.15  # Same penalty for Poisson draws
        dist_map[key] = dist_map.get(key, 0) + val
    
    import random as _ens_rng
    merged_dist = []
    for k, v in sorted(dist_map.items(), key=lambda x: -x[1])[:6]:
        h, a = k.split("-")
        prob = max(3, round(v, 1))
        merged_dist.append({"home": int(h), "away": int(a), "prob": prob})
    
    # Sample from the merged distribution for the headline prediction
    # If top merged score is a draw, prefer LLM's decisive outcome if available
    if merged_dist and merged_dist[0]["home"] == merged_dist[0]["away"]:
        llm_top = llm_pred.get("predicted_home_goals"), llm_pred.get("predicted_away_goals")
        if llm_top[0] is not None and llm_top[1] is not None and llm_top[0] != llm_top[1]:
            # LLM prefers decisive outcome — boost non-draw scores
            draw_score = merged_dist[0]
            non_draws = [d for d in merged_dist if d["home"] != d["away"]]
            if non_draws:
                # Sample from non-draws with temperature for variety
                ens_hg, ens_ag = sample_prediction(non_draws[:4], temperature=2.0)
            else:
                ens_hg, ens_ag = sample_prediction(merged_dist, temperature=2.0)
        else:
            ens_hg, ens_ag = sample_prediction(merged_dist)
    else:
        ens_hg, ens_ag = sample_prediction(merged_dist if merged_dist else 
            [{"home":1,"away":1,"prob":50},{"home":2,"away":0,"prob":30},{"home":0,"away":2,"prob":20}])
    
    # Reject draws for knockout — resample if needed
    for _ in range(5):
        if ens_hg != ens_ag:
            break
        ens_hg, ens_ag = sample_prediction(merged_dist if merged_dist else
            [{"home":1,"away":0,"prob":50},{"home":2,"away":1,"prob":30},{"home":2,"away":0,"prob":20}], temperature=2.0)
    
    # Gap-aware correction: close matches shouldn't have blowout predictions
    hr = float(llm_pred.get("market_home_prob", 0.4))
    ar = float(llm_pred.get("market_away_prob", 0.3))
    gap = abs(hr - ar)
    # For close matches (gap < 0.15), cap max score at 2 for either team
    if gap < 0.12 and ens_hg > 2:
        ens_hg = 2
    if gap < 0.12 and ens_ag > 2:
        ens_ag = 2
    if gap < 0.20 and ens_hg >= 3 and ens_ag == 0:
        # Very close match with blowout — reduce to 2-0 at most
        ens_hg = min(ens_hg, 2)
    
    # Also blend model-level confidences and probabilities
    llm_conf = float(llm_pred.get("confidence", 0.7))
    stat_conf = float(stat_pred.get("confidence", 0.7))
    conf = round(llm_conf * llm_weight + stat_conf * (1 - llm_weight), 2)
    
    # Market probabilities: blend both models, ensure no 0%
    mp_home = max(0.05, min(0.85, 
        float(llm_pred.get("market_home_prob", 0.35)) * llm_weight +
        float(stat_pred.get("market_home_prob", 0.35)) * (1 - llm_weight)))
    mp_draw = max(0.05, min(0.85,
        float(llm_pred.get("market_draw_prob", 0.25)) * llm_weight +
        float(stat_pred.get("market_draw_prob", 0.25)) * (1 - llm_weight)))
    mp_away = max(0.05, min(0.85,
        float(llm_pred.get("market_away_prob", 0.35)) * llm_weight +
        float(stat_pred.get("market_away_prob", 0.35)) * (1 - llm_weight)))
    
    # Normalize to 100%
    total_mp = mp_home + mp_draw + mp_away
    if total_mp > 0:
        mp_home = round(mp_home / total_mp, 3)
        mp_draw = round(mp_draw / total_mp, 3)
        mp_away = round(mp_away / total_mp, 3)
    
    # Build confidence basis
    llm_basis = llm_pred.get("confidence_basis", "LLM分析")
    stat_basis = stat_pred.get("confidence_basis", "泊松模型")
    merged_basis = f"集成 (LLM×{llm_weight} + Poisson×{1-llm_weight}): {llm_basis}"
    
    return {
        "home_team": llm_pred.get("home_team", ""),
        "away_team": llm_pred.get("away_team", ""),
        "model": "Ensemble (LLM+Poisson)",
        "predicted_home_goals": ens_hg,
        "predicted_away_goals": ens_ag,
        "confidence": conf,
        "score_distribution": merged_dist,
        "reasoning": llm_pred.get("reasoning", []) + stat_pred.get("reasoning", []),
        "confidence_basis": merged_basis,
        "llm_generated": llm_pred.get("llm_generated", False),
        "market_home_prob": mp_home,
        "market_draw_prob": mp_draw,
        "market_away_prob": mp_away,
        "odds_detail": llm_pred.get("odds_detail", {}),
        "odds_sources_used": llm_pred.get("odds_sources_used", 
            len(llm_pred.get("odds_detail", {}))),
        "commentator_count": llm_pred.get("commentator_count", 0),
        "x_factor": llm_pred.get("x_factor", stat_pred.get("x_factor", "")),
        "home_lambda": stat_pred.get("home_lambda", 0),
        "away_lambda": stat_pred.get("away_lambda", 0),
    }


def sample_prediction(score_dist, temperature=2.0):
    """Sample a score from the distribution with temperature scaling.
    
    Higher temperature = more variety (flattens the distribution).
    Lower temperature = more likely to pick the top score.
    Temperature 1.8 means the 2nd and 3rd choices get significantly more weight.
    """
    import random, math
    if not score_dist:
        return 1, 1
    # Apply temperature: raise each prob to (1/temperature) to flatten
    probs = [math.pow(max(d['prob'], 1), 1.0 / temperature) for d in score_dist]
    total = sum(probs)
    r = random.uniform(0, total)
    cumulative = 0
    for i, d in enumerate(score_dist):
        cumulative += probs[i]
        if r <= cumulative:
            return d['home'], d['away']
    return score_dist[-1]['home'], score_dist[-1]['away']
