if select(2,UnitClass("player"))~="PALADIN" then return end
-- Canonicalize English Forever equip stats for GearMatic's API/tooltip merge.
-- The sim and imported scale use rating: 1% hit = 10, crit = 14, expertise = 10.
local gm = GearMatic
local compat = gm and gm.Compat
local norm = gm and gm.Scoring2 and gm.Scoring2.Normalize
if not norm or not compat or not (compat.IsForever or compat.Flavor == "forever") then return end
if norm.retSimForeverPercentReader then return end
norm.retSimForeverPercentReader = true
local original = norm.ExtractFromLine
local rows = {
    -- This is generic power, not damage-only power. The API already calls it
    -- spellpower; returning spelldamage would let the merge count it twice.
    {"^Increases damage and healing done by magical spells and effects by up to (%d+)%.$", "spellpower", 1},
    {"^Improves your chance to hit by ([%d%.,]+)%%%.$", "hitrating", 10},
    {"^Improves your chance to get a critical strike by ([%d%.,]+)%%%.$", "critrating", 14},
    {"^Improves your chance to get a critical strike with all spells and attacks by ([%d%.,]+)%%%.$", "critrating", 14},
    {"^Increases your expertise by ([%d%.,]+)%%%.$", "expertiserating", 10},
    {"^Reduces the chance for enemies to dodge or parry your attacks by ([%d%.,]+)%%%.$", "expertiserating", 10},
    {"^Reduces chance to be Dodged or Parried by ([%d%.,]+)%%%.$", "expertiserating", 10},
    {"^Increases your attack speed by ([%d%.,]+)%%%.$", "hasterating", 10},
    {"^Increases your haste by ([%d%.,]+)%%%.$", "hasterating", 10},
    {"^Restores ([%d%.,]+) mana per 5 sec%.$", "mp5", 1},
    {"^Restores ([%d%.,]+) health per 5 sec%.$", "hp5", 1},
    {"^Increases attack power by ([%d%.,]+)%.$", "attackpower", 1},
    {"^%+([%d%.,]+) Attack Power%.$", "attackpower", 1},
    {"^%+([%d%.,]+) Attack Power%. This effect is tripled in Forest and Grassland areas%.$", "attackpower", 1},
    {"^Decreases the magical resistances of your spell targets by ([%d%.,]+)%.$", "spellpenetration", 1},
    {"^Your attacks ignore ([%d%.,]+) of your opponent's armor%.$", "armorpen", 1},
    {"^Increases your armor penetration rating by ([%d%.,]+)%.$", "armorpen", 1},
    {"^Increases damage done by magical spells and effects by up to ([%d%.,]+)%.$", "spelldamage", 1},
}
for _, school in ipairs({"Holy", "Fire", "Frost", "Nature", "Shadow", "Arcane"}) do
    rows[#rows + 1] = {"^Increases damage done by " .. school .. " spells and effects by up to ([%d%.,]+)%.$", school:lower() .. "spelldamage", 1}
end
for label, key in pairs({["hit"]="hitrating", ["critical strike"]="critrating", ["haste"]="hasterating",
    ["expertise"]="expertiserating", ["spell penetration"]="spellpenetration"}) do
    rows[#rows + 1] = {"^Improves " .. label .. " rating by ([%d%.,]+)%.$", key, 1}
    rows[#rows + 1] = {"^Increases your " .. label .. " rating by ([%d%.,]+)%.$", key, 1}
end
local mapOriginal = norm.MapStatKey
local resistanceKeys = {RESISTANCE2_NAME="fireresist", RESISTANCE3_NAME="natureresist",
    RESISTANCE4_NAME="frostresist", RESISTANCE5_NAME="shadowresist", RESISTANCE6_NAME="arcaneresist",
    ITEM_MOD_DAMAGE_PER_SECOND_SHORT="dps", ITEM_MOD_DAMAGE_PER_SECOND="dps",
    ITEM_MOD_POWER_REGEN0_SHORT="mp5", ITEM_MOD_HEALTH_REGENERATION_SHORT="hp5"}
if mapOriginal then
    norm.MapStatKey = function(key) return resistanceKeys[key] or mapOriginal(key) end
end
norm.ExtractFromLine = function(text)
    if type(text) ~= "string" then return end
    local clean = text:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")
    clean = clean:gsub("^%s*Equip:%s*", ""):gsub("^%s+", ""):gsub("%s+$", "")
    for _, row in ipairs(rows) do
        local n = clean:match(row[1])
        n = n and tonumber((n:gsub(",", ".")))
        if n then return row[2], n * row[3] end
    end
    return original(text)
end
