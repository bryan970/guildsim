if select(2,UnitClass("player"))~="PALADIN" then return end
-- Local compatibility policy: kept outside GearMatic so addon updates preserve it.
local _, ns = ...
local gm = GearMatic
local s2 = gm and gm.Scoring2
if not s2 or not gm.Compat or not (gm.Compat.IsForever or gm.Compat.Flavor == "forever") then
    ns.VerifyWeights = function() return false, "GearMatic compatibility API unavailable; scoring adapters were not installed." end
    ns.Audit = function() print("Ret Sim audit: CHECK: GearMatic compatibility API unavailable.") end
    return
end
ns.policyIssues = {}
local function imported(scale)
    return scale and scale.weights and next(scale.weights)
        and (scale.source == "pasted" or scale.source == "pawn")
end
local function ownScale(scale)
    return imported(scale) and scale.name and scale.name:match("^Ret60 UW ") ~= nil
end
ns.IsSimScale = ownScale
local function sanitize(result)
    if result ~= nil and type(result) ~= "table" then
        ns.policyIssues[#ns.policyIssues + 1] = "Unexpected comparison API return type"
        return nil
    end
    if result and imported(result.scale) and (result.procNotScored or result.baseProcNotScored)
        and result.tierVerdictBasis ~= "weights" then
        result.tierVerdict, result.tierVerdictBasis, result.tierPct = nil, nil, nil
        result.delta, result.rankDelta = 0, 0
        result.fallback = false -- an imported scale exists; the effect is unscored
        result.retSimUnscored = true
    end
    return result
end
local compare = s2.Compare
local function cannotUse(charKey,link)
    local currentKey=gm.Compat.CurrentCharKey and gm.Compat.CurrentCharKey()
    return charKey==currentKey and ns.ItemEligibility and ns.ItemEligibility(link)==false
end
local function weaponVerdict(result,charKey,link,loc)
    local currentKey=gm.Compat.CurrentCharKey and gm.Compat.CurrentCharKey()
    if charKey==currentKey and ns.ItemEligibility and ns.ItemEligibility(link)==false then return nil end
    if not result or not ownScale(result.scale) or charKey~=currentKey then return result end
    if ns.IsItemSimSupported and ns.IsItemSimSupported(link) then
        local full=ns.ItemComparison(link)
        result.tierVerdict,result.tierVerdictBasis,result.tierPct=nil,nil,nil
        result.setNotScored=nil;result.fallback=false
        if full and not full.provisional then
            result.candidate=full.dps;result.equipped=full.baselineDps
            result.delta=full.uncertain and 0 or full.percent;result.statDelta=result.delta;result.rankDelta=result.delta
            result.procNotScored=nil;result.baseProcNotScored=nil;result.retSimUnscored=nil
            result.retSimFullItem=true
        else
            return nil -- The shared tooltip states the actual missing/stale reason.
        end
        return result
    end
    if loc~="INVTYPE_2HWEAPON" then
        local fresh=not ns.ProjectionWeightsFresh or ns.ProjectionWeightsFresh(result.scale.name)
        if not fresh then
            result.delta=0;result.statDelta=0;result.rankDelta=0
            result.tierVerdict=nil;result.tierVerdictBasis=nil;result.tierPct=nil
            result.fallback=false;result.retSimWeightsStale=true
        end
        return result
    end
    local full=ns.WeaponComparison and ns.WeaponComparison(link)
    result.tierVerdict,result.tierVerdictBasis,result.tierPct=nil,nil,nil
    result.setNotScored=nil
    if full and not full.provisional then
        result.candidate=full.dps;result.equipped=full.baselineDps
        result.delta=full.uncertain and 0 or full.percent;result.statDelta=result.delta;result.rankDelta=result.delta
        result.procNotScored=nil;result.baseProcNotScored=nil;result.fallback=false
        result.retSimFullWeapon=true;result.retSimUnscored=nil
    else
        return nil
    end
    return result
end
if compare then
    for _, key in ipairs({"EvaluateForChar", "EvaluateAgainstScale", "EvaluateVsEquipped"}) do
        local original = compare[key]
        if original then compare[key] = function(...)
            local charKey,_,link,loc=...
            if cannotUse(charKey,link) then return nil end
            return weaponVerdict(sanitize(original(...)),charKey,link,loc)
        end
        else ns.policyIssues[#ns.policyIssues + 1] = "Missing Compare." .. key end
    end
    if compare.BestAltEvalAcrossSpecs then
        local original = compare.BestAltEvalAcrossSpecs
        compare.BestAltEvalAcrossSpecs = function(...)
            local charKey,link,loc=...
            if cannotUse(charKey,link) then return nil,0 end
            local result, pct = original(...)
            result = sanitize(result)
            result=weaponVerdict(result,charKey,link,loc)
            if result and (result.retSimFullWeapon or result.retSimWeaponRequired or result.retSimFullItem or result.retSimItemRequired) then pct=result.delta end
            if result and result.retSimUnscored then pct = 0 end
            return result, pct
        end
    end
    local swap = compare.SwapFallbackVerdict
    if swap then
        compare.SwapFallbackVerdict = function(candidate, baseline, scale)
            if ownScale(scale) then
                if ns.IsItemSimSupported and ns.IsItemSimSupported(candidate) then
                    local full=ns.ItemComparison(candidate)
                    if full and not full.provisional and not full.uncertain then
                        return true,full.percent>0.1 and "up" or (full.percent< -0.1 and "down" or nil),"fullsim",full.percent,false
                    end
                    return true,nil,nil,nil,false
                end
                local info=(C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
                local loc
                if info then local _,_,_,equipLoc=info(candidate);loc=equipLoc end
                if loc=="INVTYPE_2HWEAPON" then
                    local full=ns.WeaponComparison and ns.WeaponComparison(candidate)
                    if full and not full.provisional and not full.uncertain then
                        return true, full.percent>0.1 and "up" or (full.percent< -0.1 and "down" or nil), "fullsim", full.percent, false
                    end
                    return true,nil,nil,nil,false
                end
            end
            if imported(scale) then
                local applied, _, _, _, baseFlagged = swap(candidate, baseline, scale)
                if applied then return true, nil, nil, nil, baseFlagged end
                return false
            end
            return swap(candidate, baseline, scale)
        end
    else ns.policyIssues[#ns.policyIssues + 1] = "Missing Compare.SwapFallbackVerdict" end
else ns.policyIssues[#ns.policyIssues + 1] = "Missing scoring comparison API" end

local score = s2.Score
if score and score.ScoreItem and score.StatScore then
    local original = score.ScoreItem
    score.ScoreItem = function(link, scale, cached, ilvl)
        -- Imported weights must not become guide/tier scores at level 60.
        if imported(scale) then return score.StatScore(link, scale, cached, ilvl) end
        return original(link, scale, cached, ilvl)
    end
else ns.policyIssues[#ns.policyIssues + 1] = "Missing scoring API" end

local si = gm.ScaleImport
if si and si.GetScalesForClass and si.GetActiveScale then
    local original = si.GetScalesForClass
    si.GetScalesForClass = function(charKey)
        local scales = original(charKey)
        local active = si.GetActiveScale(charKey)
        if not ownScale(active) then return scales end
        -- Imported profiles of the same spec used to win by pairs() order.
        local out = {active}
        for _, scale in ipairs(scales or {}) do
            local sameSpec = scale.class == active.class and
                ((scale.specID and active.specID and scale.specID == active.specID)
                 or tostring(scale.spec):lower() == tostring(active.spec):lower())
            if not sameSpec then out[#out + 1] = scale end
        end
        return out
    end
else ns.policyIssues[#ns.policyIssues + 1] = "Missing active-scale API" end

function ns.SelectedWeightPayload()
    return GuildSimBetaDB and GuildSimBetaDB.weightView=="target" and ns.targetWeights or ns.payload
end
function ns.VerifyWeights(explicit)
    local p = explicit or ns.SelectedWeightPayload()
    if not p then return false, "No sim payload loaded." end
    if UnitGUID("player") ~= p.guid then return false, "Sim payload belongs to another character." end
    if not p.generated or time() - p.generated > 7 * 86400 then return false, "Sim result is missing its date or is over a week old." end
    if ns.CheckPayload then local valid,why=ns.CheckPayload(p);if not valid then return false,why end end
    if not si or not si.ParseScale or not si.GetActiveScale then return false, "Weight API unavailable." end
    local expected = si.ParseScale(p.pawn)
    local key = gm.Compat.CurrentCharKey and gm.Compat.CurrentCharKey()
    local actual = key and si.GetActiveScale(key)
    if not actual or not expected or not actual.weights or actual.name ~= expected.name then return false, "Active GearMatic profile differs from the sim profile." end
    for stat, value in pairs(expected.weights) do
        if type(actual.weights[stat]) ~= "number" or math.abs(actual.weights[stat] - value) > 0.000002 then
            return false, "Weight mismatch: " .. stat
        end
    end
    for stat, value in pairs(actual.weights) do
        if expected.weights[stat] == nil and value ~= 0 then return false, "Unexpected weight: " .. stat end
    end
    if #ns.policyIssues > 0 then return false, table.concat(ns.policyIssues, "; ") end
    return true, "Loaded weights match the sim; stat and recommendation adapters are active."
end

-- Run small capability probes on every load. Future incompatible APIs are
-- reported instead of silently claiming the weight import is healthy.
local probes = {
    {"Equip: Improves your chance to hit by 0.7%.", "hitrating", 7},
    {"Equip: Improves your chance to get a critical strike by 0.5%.", "critrating", 7},
    {"Equip: Increases damage and healing done by magical spells and effects by up to 16.", "spellpower", 16},
    {"Equip: Restores 5 mana per 5 sec.", "mp5", 5},
}
local norm = s2.Normalize
if norm and norm.retSimForeverPercentReader and norm.ExtractFromLine then
    for _, probe in ipairs(probes) do
        local ok, key, value = pcall(norm.ExtractFromLine, probe[1])
        if not ok or key ~= probe[2] or value ~= probe[3] then
            ns.policyIssues[#ns.policyIssues + 1] = "Stat reader probe failed: " .. probe[2]
        end
    end
else ns.policyIssues[#ns.policyIssues + 1] = "Forever stat adapter is unavailable" end

function ns.Audit()
    local ok, why = ns.VerifyWeights()
    print("|cffead36cRet Sim audit:|r " .. (ok and "PASS: " or "CHECK: ") .. why)
    local p = ns.SelectedWeightPayload()
    if p then print("Ret Sim: " .. p.mode .. "; run " .. tostring(p.runId):sub(1,12) .. ". Full fight sims include hit and misses. Imported GearMatic item weights are fixed; update sims after gear changes.") end
    local key = gm.Compat.CurrentCharKey and gm.Compat.CurrentCharKey()
    local actual = si and si.GetActiveScale and key and si.GetActiveScale(key)
    if actual and actual.weights then
        print(string.format("Ret Sim active: %s; Strength %.3f, Spell Power %.3f, Hit/rating %.3f, MP5 %.3f",
            actual.name or "?", actual.weights.strength or 0, actual.weights.spellpower or 0,
            actual.weights.hitrating or 0, actual.weights.mp5 or 0))
    end
end
