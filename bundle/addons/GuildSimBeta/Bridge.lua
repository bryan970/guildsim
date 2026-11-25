if select(2,UnitClass("player"))~="PALADIN" then return end
local _, ns = ...
ns.SameCombatExport=ns.SameCombatExport or function(a,b)return type(a)=="string" and a==b end
local function say(s) print("|cffead36cRet Sim:|r " .. s) end
local function exporter()
    if not LibStub then return end
    local lib = LibStub("AceAddon-3.0", true)
    return lib and lib:GetAddon("WowSimsExporter", true)
end
local function check(p)
    if not p then return false, "No result yet. Run the local Ret Sim helper." end
    if ns.engineCommit and (not p.wowsims or p.wowsims.upstream_commit~=ns.engineCommit) then return false,"Simulation engine updated. Use Update sims in /guildsim to refresh results." end
    if UnitGUID("player") ~= p.guid then return false, "Result belongs to another character." end
    if time() - p.generated > 7 * 86400 then
        if p==ns.targetWeights then return false,"Final-target weights are over a week old. Run Run Target Weights.cmd, then /reload." end
        return false, "Result is over a week old. Run the helper again."
    end
    -- Planning simulates its fixed target gear/talents, not worn leveling gear.
    -- Keep the character/age gates; exact live export equality is for current sims.
    if p.mode == "planning" and p.context~="equipped" then return true end
    local addon = exporter()
    if not addon or not addon.BuildExport then return false, "WoWSims Exporter is not ready." end
    local ok, live = ns.ReadExport(addon,false)
    if not ok or not live then return false, "Could not read your character. Try /guildsim again in a few seconds." end
    if not ns.SameCombatExport(live,p.sourceExport) then return false, "Combat gear or talents changed. Use Update sims in /guildsim." end
    return true
end
ns.CheckPayload=check
local function applyBis(p, explicit)
    if explicit and ns.ShowGearBrowser then ns.ShowGearBrowser("gear") end
end
local function apply(planning,explicit)
    if _G.RetSimBridgeDB then return end -- Preview mode until the verified personal migration finishes.
    local p = explicit or ns.payload
    local ok, why = check(p)
    if not ok then say(why); return end
    applyBis(p, planning)
    if p.mode == "planning" and not planning then
        say("Level-60 PLANNING weights ready. /guildsim planning imports them explicitly. These are not weights for your current level.")
        return
    end
    if p.mode == "current" and UnitLevel("player") ~= 60 then say("This result requires level 60."); return end
    local si = GearMatic and GearMatic.ScaleImport
    if not si or not si.HandleSlash or not si.ParseScale then say("GearMatic import API unavailable."); return end
    local scale = si.ParseScale(p.pawn)
    if not scale then say("Generated scale did not parse. No weights changed."); return end
    GuildSimBetaDB = GuildSimBetaDB or {}
    local key = UnitGUID("player")
    local weightsMatch = ns.VerifyWeights and ns.VerifyWeights(p)
    if GuildSimBetaDB[key] == p.runId and not planning and weightsMatch then return end
    -- Keep a recovery copy of the prior scale selection; never edit addon defaults.
    local charKey = GearMatic.Compat and GearMatic.Compat.CurrentCharKey()
    if charKey and GearMaticDB and GearMaticDB.scales then
        GuildSimBetaDB.previous = GuildSimBetaDB.previous or {}
        if not GuildSimBetaDB.previous[key] then
            local bag = GearMaticDB.scales[charKey]
            GuildSimBetaDB.previous[key] = {active = bag and bag._active, builtin = bag and bag._builtin}
        end
    end
    si.HandleSlash(p.pawn)
    GuildSimBetaDB.weightView=p==ns.targetWeights and "target" or "equipped"
    if planning and p.mode == "planning" then GuildSimBetaDB.planningEnabled = true end
    GuildSimBetaDB[key] = p.runId
    if ns.VerifyWeights then
        local verified, problem = ns.VerifyWeights(p)
        if not verified then say("Import needs attention: " .. problem); return end
    end
    say((p.mode == "planning" and "PLANNING " or "") .. "weights imported. " .. p.scenario .. ". Full sims include hit caps; imported GearMatic weights stay fixed until Update sims.")
end
SLASH_GUILDSIMRETBRIDGE1 = "/guildsim"
SlashCmdList.GUILDSIMRETBRIDGE = function(arg)
    if arg == "" then ns.ShowGearBrowser("gear")
    elseif arg == "planning" then apply(true)
    elseif arg == "update" then ns.SmartSync()
    elseif arg == "targetweights" then
        if ns.targetWeights then apply(true,ns.targetWeights) else say("The final-target weight reference is unavailable.") end
    elseif arg == "equipped" then apply(true)
    elseif arg == "progress" then ns.ShowProgress()
    elseif arg == "perf" then ns.Performance()
    elseif arg == "results" then ns.ShowResults()
    elseif arg == "items" then ns.ShowItemResults()
    elseif arg == "trinkets" then ns.ShowTrinketPairs()
    elseif arg:match("^trinket%s+") then ns.EditTrinketPool(arg:match("^trinket%s+(.+)$"),false);ns.ShowTrinketPairs()
    elseif arg:match("^item%s+") then ns.QueueItems(arg:match("^item%s+(.+)$"));ns.ShowProgress()
    elseif arg == "weapons" then ns.QueueWeapons()
    elseif arg == "clearweapons" then ns.ClearWeapons()
    elseif arg:match("^weapon%s+") then ns.QueueWeapons(arg:match("^weapon%s+(.+)$"))
    elseif arg == "audit" then if ns.Audit then ns.Audit() else say("Audit adapter is unavailable.") end
    elseif arg == "bis" then
        local ok, why = check(ns.payload)
        if ok then applyBis(ns.payload, true) else say(why) end
    elseif arg == "bisoff" then
        say("GuildSimBeta uses its own gear browser and character panel.")
    elseif arg == "apply" then apply(false)
    elseif arg == "farm" then ns.ShowFarm()
    elseif arg == "target" then ns.ImportTarget()
    elseif arg == "save" then
        local addon = exporter()
        if addon and addon.BuildExport then
            local ok = ns.ReadExport(addon,true)
            say(ok and "Export captured. /reload to save it, then run the local helper." or "Export failed; try /wse export.")
        end
    else
        local ok, why = check(ns.payload)
        if ok then
            say(ns.payload.mode .. " result ready: " .. ns.payload.scenario .. ". /guildsim apply, /guildsim planning, /guildsim save.")
        else say(why) end
    end
end
local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function()
    C_Timer.After(5, function()
        local addon = exporter()
        if addon and addon.BuildExport then ns.ReadExport(addon,true) end
        if ns.InvalidateSimFreshness then ns.InvalidateSimFreshness() end
        if ns.payload then
            local acceptedPlanning = GuildSimBetaDB and (GuildSimBetaDB.planningEnabled
                or GuildSimBetaDB[UnitGUID("player")] == ns.payload.runId)
            local selected=ns.SelectedWeightPayload and ns.SelectedWeightPayload() or ns.payload
            apply(selected.mode == "planning" and acceptedPlanning or false,selected)
            if ns.Audit then ns.Audit() end
        end
    end)
end)

local function planForPlayer()
    local p = ns.payload
    if not p or UnitGUID("player") ~= p.guid then say("No farming plan for this character is loaded."); return end
    if not p.plan or not p.plan.items then say("Run the helper with the pre-raid target set first."); return end
    return p.plan
end

function ns.ImportTarget()
    local plan = planForPlayer()
    if not plan then return end
    local store = GearMatic and GearMatic.Loadouts and GearMatic.Loadouts.Store
    if not store or not store.Save then
        say("GearMatic's loadout store is unavailable. /guildsim farm still shows the checklist."); return
    end
    local entry = {name = plan.name, icon = "interface\\icons\\spell_holy_sealofmight", slots = {}, ignore = {[4] = true, [17] = true, [19] = true}}
    for _, row in ipairs(plan.items) do
          local link = "|Hitem:" .. row.id .. ":" .. (row.enchant or 0) .. ":0:0:0:0:" .. (row.random_suffix or 0) .. ":0:60:0:0:0:0|h[" .. row.name .. "]|h"
        entry.slots[row.wow_slot] = {itemID = row.id, itemLink = link}
    end
    -- Save returns the native stored table. Populate only this named target's slots.
    local imported, why = store.Save(plan.name, {iconOverride = entry.icon})
    if not imported then say("Target save failed: " .. tostring(why)); return end
    imported.slots = entry.slots; imported.ignore = entry.ignore
    imported.hashVersion = nil
    if store.Get then store.Get(plan.name) end
    say("Saved GearMatic loadout: " .. plan.name .. ". Open /gm to inspect it. Nothing was equipped. /guildsim farm shows sources and ownership.")
end

local farmFrame
local function itemCount(id)
    local fn = C_Item and C_Item.GetItemCount or GetItemCount
    if not fn then return 0 end
    local ok, count = pcall(fn, id, true)
    if not ok or type(count) ~= "number" then return 0 end
    if issecretvalue and issecretvalue(count) then return 0 end
    return count
end
function ns.ShowFarm()
    local plan = planForPlayer()
    if not plan then return end
    if not farmFrame then
        local f = CreateFrame("Frame", "GuildSimBetaFarmFrame", UIParent, "BackdropTemplate")
        farmFrame = f
        f:SetSize(800, 740); f:SetPoint("CENTER"); f:SetFrameStrata("DIALOG")
        f:SetBackdrop({bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 24, insets = {left = 6, right = 6, top = 6, bottom = 6}})
        f:EnableMouse(true); f:SetMovable(true); f:RegisterForDrag("LeftButton")
        f:SetScript("OnDragStart", f.StartMoving); f:SetScript("OnDragStop", f.StopMovingOrSizing)
        local close = CreateFrame("Button", nil, f, "UIPanelCloseButton"); close:SetPoint("TOPRIGHT", -5, -5)
        local title = f:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge"); title:SetPoint("TOPLEFT", 24, -22)
        title:SetText("Ret60 Unsealed Wrath â€” farming targets")
        local desc = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall"); desc:SetPoint("TOPLEFT", 24, -50); desc:SetWidth(745); desc:SetJustifyH("LEFT")
        desc:SetText("Horde pre-raid plan. Priority 1 = convenient early targets; 3 = longer or expensive goals.\nHover for item stats and GearMatic scoring. Ownership includes equipped items, bags and cached bank.")
        f.rows = {}
        for i = 1, 16 do
            local b = CreateFrame("Button", nil, f); b:SetPoint("TOPLEFT", 24, -88 - (i - 1) * 33); b:SetSize(746, 32)
            b.item = b:CreateFontString(nil, "OVERLAY", "GameFontNormal"); b.item:SetPoint("TOPLEFT"); b.item:SetWidth(735); b.item:SetJustifyH("LEFT")
            b.source = b:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall"); b.source:SetPoint("TOPLEFT", 14, -16); b.source:SetWidth(725); b.source:SetJustifyH("LEFT")
            b:SetScript("OnEnter", function(self) if self.target then GameTooltip:SetOwner(self, "ANCHOR_RIGHT"); GameTooltip:SetHyperlink("item:" .. self.target.id); GameTooltip:Show() end end)
            b:SetScript("OnLeave", function() GameTooltip:Hide() end)
            f.rows[i] = b
        end
        local target = CreateFrame("Button", nil, f, "UIPanelButtonTemplate"); target:SetPoint("BOTTOMLEFT", 24, 26); target:SetSize(235, 25); target:SetText("Save target in GearMatic")
        target:SetScript("OnClick", ns.ImportTarget)
        local refresh = CreateFrame("Button", nil, f, "UIPanelButtonTemplate"); refresh:SetPoint("LEFT", target, "RIGHT", 12, 0); refresh:SetSize(120, 25); refresh:SetText("Refresh")
        refresh:SetScript("OnClick", function() ns.ShowFarm() end)
        local note = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall"); note:SetPoint("BOTTOMLEFT", 24, 64); note:SetWidth(745); note:SetJustifyH("LEFT")
        note:SetText("Targets were compared as complete sets in the local simulator. This is a starting plan, not guaranteed universal BiS.\nThe sim report contains alternatives and assumptions. This checklist does not equip or buy anything.")
        if UISpecialFrames then table.insert(UISpecialFrames, "GuildSimBetaFarmFrame") end
    end
    local rows = {}
    for _, row in ipairs(plan.items) do rows[#rows + 1] = row end
    table.sort(rows, function(a, b) if a.priority == b.priority then return a.wow_slot < b.wow_slot end; return a.priority < b.priority end)
    for i, button in ipairs(farmFrame.rows) do
        local row = rows[i]
        if row then
            button.target = row
            local owned = itemCount(row.id) > 0
            local status = owned and "|cff70dd70OWNED|r" or "|cffffcc66FARM|r"
            button.item:SetText(status .. "  " .. row.priority .. ". " .. row.slot .. ": " .. row.name)
            button.source:SetText(row.where); button:Show()
        else button:Hide() end
    end
    farmFrame:Show()
end

local function addFarmTooltip(tooltip, data)
    if not tooltip or not ns.payload or UnitGUID("player") ~= ns.payload.guid then return end
    local plan = ns.payload.plan
    if not plan then return end
    local id = data and data.id
    if not id and tooltip.GetItem then local _, link = tooltip:GetItem(); id = link and tonumber(link:match("item:(%d+)")) end
    if not id or (issecretvalue and issecretvalue(id)) then return end
    for _, row in ipairs(plan.items) do
        if row.id == id then
            tooltip:AddLine("Ret60 pre-raid farming target", 1, 0.82, 0.35)
            tooltip:AddLine(row.where, 0.85, 0.85, 0.85, true)
            break
        end
    end
end
if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(t, d) pcall(addFarmTooltip, t, d) end)
elseif GameTooltip and GameTooltip.HookScript then
    pcall(function() GameTooltip:HookScript("OnTooltipSetItem", function(t) pcall(addFarmTooltip, t) end) end)
end
