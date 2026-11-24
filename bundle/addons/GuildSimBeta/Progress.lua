if select(2,UnitClass("player"))~="PALADIN" then return end
local _, ns = ...
ns.SameCombatExport=ns.SameCombatExport or function(a,b)return type(a)=="string" and a==b end
local window, capturedThisSession, pendingReload, reloadAttempt
local function reloadHelp(reason)
    if not pendingReload then return end
    pendingReload=nil
    local message="Reload did not complete. Type /reload in chat and press Enter. "..(reason or "")
    print("|cffead36cRet Sim:|r "..message)
    if window then
        window.title:SetText("Manual reload needed")
        window.detail:SetText(message)
        window.primary:SetText("Reload retry / manual help")
    end
    if ChatFrame_OpenChat then pcall(ChatFrame_OpenChat,"/reload") end
end

local function covered(context)
    if ns.weaponResults and ns.weaponResults.catalogMode then return true end
    local queues = GuildSimBetaDB and GuildSimBetaDB.weaponQueue
    for _, item in pairs(queues and queues[UnitGUID("player")] or {}) do
        local found
        for _, row in ipairs(context.weapons or {}) do
            if row.id == item.id and (row.randomSuffix or 0) == (item.randomSuffix or 0) then found = true end
        end
        for _, row in ipairs(context.errors or {}) do
            if row.id == item.id then found = true end -- A reported unsupported item is resolved, not silently scored.
        end
        if not found then return false end
    end
    return true
end

function ns.ProgressState()
    if capturedThisSession then
        return 1, "Capture ready", "Click Save capture to reload and let the helper read it.", "save"
    end
    local weightsReady = ns.CheckPayload and ns.CheckPayload(ns.payload)
    local context, result
    if ns.WeaponData then context, result = ns.WeaponData("equipped") end
    if weightsReady and context and covered(context, result) and (not ns.ItemsCovered or ns.ItemsCovered()) then
        local verified,why=true,nil
        if ns.VerifyWeights then verified,why=ns.VerifyWeights(ns.payload) end
        if not verified then return 2,"Results loaded — apply weights",why or "Click Apply loaded weights.","apply" end
        return 3, "Up to date", "Ret weights, weapons, armor and jewelry results match your capture. Scoring was checked automatically.", "capture"
    end
    local requests=GuildSimBetaDB and GuildSimBetaDB.progressRequests
    if requests and requests[UnitGUID("player")] then
        local request=requests[UnitGUID("player")]
        if type(request)=="table" and request.sourceExport and ns.LiveSimExport then
            local live=ns.LiveSimExport()
            if live and not ns.SameCombatExport(live,request.sourceExport) then
                return 2,"Character changed since capture","Click Update sims to save your latest gear and talents.","capture"
            end
        end
        if type(request)=="table" and request.inventorySignature and ns.QuickInventorySignature
            and request.inventorySignature~=ns.QuickInventorySignature() then
            return 2,"Equipment inventory changed since capture","Click Update sims to include the newer bag items or focused requests.","capture"
        end
        return 2, "Waiting for the simulator", "Keep playing. When the desktop Ret Sim Progress window says Ready to reload, click Load results below. WoW cannot see the helper's live progress.", "load"
    end
    if ns.ItemCapturePending and ns.ItemCapturePending() then return 2,"New gear or items detected","Click Update sims to save your collected items and current gear.","capture" end
    if ns.itemResults and ns.itemResults.catalogMode and not ns.itemResults.complete then
        if ns.itemResults.scope=="quick" then return 2,"Quick comparisons updating","Keep playing; load results when the desktop helper says ready.","load" end
        return 2,"Full equipment catalog running",string.format("%d/%d variants loaded. Keep playing; load newer results when the desktop helper is ready.",ns.itemResults.completedVariants or 0,ns.itemResults.catalogVariants or 0),"load"
    end
    return 2, "Update needed", "Click Update sims to capture your gear, talents and bag equipment, then reload. The desktop helper does the rest.", "capture"
end

function ns.SmartSync()
    local ok,step,title,detail,action=pcall(ns.ProgressState)
    if not ok then print("|cffead36cRet Sim:|r Status check failed: "..tostring(step));return false end
    if action=="apply" then
        SlashCmdList.GUILDSIMRETBRIDGE("equipped")
        if ns.Audit then ns.Audit() end
        ns.ShowProgress()
    else
        local succeeded,result=pcall(ns.ReloadSimResults,action=="capture")
        if not succeeded then print("|cffead36cRet Sim:|r Update failed: "..tostring(result)..". Type /reload to reload the bridge.");return false end
        return result
    end
end

function ns.ReloadSimResults(capture)
    if (InCombatLockdown and InCombatLockdown()) or (UnitAffectingCombat and UnitAffectingCombat("player")) then
        print("|cffead36cRet Sim:|r Finish combat before reloading.");return false
    end
    if capture and not ns.QueueWeapons() then return false end
    if capture then
        GuildSimBetaDB=GuildSimBetaDB or {};GuildSimBetaDB.planningEnabled=true;GuildSimBetaDB.weightView="equipped"
    end
    reloadAttempt=(reloadAttempt or 0)+1;local attempt=reloadAttempt
    pendingReload=true
    local reload=(C_UI and C_UI.Reload) or ReloadUI
    if not reload then reloadHelp("The client reload API is unavailable.");return false end
    if C_Timer and C_Timer.After then
        C_Timer.After(0.75,function()
            if pendingReload and reloadAttempt==attempt then reloadHelp("The capture is kept in memory until you reload.") end
        end)
    end
    local ok,err=pcall(reload)
    if not ok then reloadHelp(tostring(err));return false end
    return true
end

function ns.ShowProgress()
    if not window then
        window = CreateFrame("Frame", "GuildSimBetaProgressFrame", UIParent, "BackdropTemplate")
        window:SetSize(570, 300); window:SetPoint("CENTER"); window:SetFrameStrata("DIALOG")
        window:SetBackdrop({bgFile="Interface\\DialogFrame\\UI-DialogBox-Background",edgeFile="Interface\\DialogFrame\\UI-DialogBox-Border",tile=true,tileSize=32,edgeSize=24,insets={left=6,right=6,top=6,bottom=6}})
        window:EnableMouse(true); window:SetMovable(true); window:RegisterForDrag("LeftButton")
        window:SetScript("OnDragStart",window.StartMoving); window:SetScript("OnDragStop",window.StopMovingOrSizing)
        local close=CreateFrame("Button",nil,window,"UIPanelCloseButton");close:SetPoint("TOPRIGHT",-5,-5)
        window.title=window:CreateFontString(nil,"OVERLAY","GameFontNormalLarge");window.title:SetPoint("TOPLEFT",22,-24)
        window.bar=CreateFrame("StatusBar",nil,window);window.bar:SetPoint("TOPLEFT",22,-58);window.bar:SetSize(526,20)
        window.bar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar");window.bar:SetStatusBarColor(.85,.65,.15);window.bar:SetMinMaxValues(0,2)
        window.count=window.bar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");window.count:SetPoint("CENTER")
        window.detail=window:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");window.detail:SetPoint("TOPLEFT",22,-90);window.detail:SetWidth(526);window.detail:SetJustifyH("LEFT")
        window.primary=CreateFrame("Button",nil,window,"UIPanelButtonTemplate")
        window.primary:SetPoint("TOPLEFT",22,-155);window.primary:SetSize(250,32);window.primary:SetScript("OnClick",ns.SmartSync)
        local results=CreateFrame("Button",nil,window,"UIPanelButtonTemplate")
        results:SetPoint("TOPLEFT",287,-155);results:SetSize(260,32);results:SetText("Gear browser");results:SetScript("OnClick",function()ns.ShowItemResults()end)
        local farm=CreateFrame("Button",nil,window,"UIPanelButtonTemplate")
        farm:SetPoint("TOPLEFT",22,-198);farm:SetSize(250,27);farm:SetText("Trinket pairs");farm:SetScript("OnClick",function()ns.ShowTrinketPairs()end)
        local more=CreateFrame("Button",nil,window,"UIPanelButtonTemplate")
        more:SetPoint("TOPLEFT",287,-198);more:SetSize(260,27);more:SetText("More options")
        window.extra={}
        more:SetScript("OnClick",function()
            window.expanded=not window.expanded;window:SetHeight(window.expanded and 420 or 300)
            for _,button in ipairs(window.extra) do button:SetShown(window.expanded) end
            more:SetText(window.expanded and "Fewer options" or "More options")
        end)
        local actions={
            {"Capture newer gear",function()ns.ReloadSimResults(true)end},
            {"Use equipped weights",function()SlashCmdList.GUILDSIMRETBRIDGE("equipped");ns.ShowProgress()end},
            {"Use farming weights",function()SlashCmdList.GUILDSIMRETBRIDGE("targetweights");ns.ShowProgress()end},
            {"Check scoring",function()if ns.Audit then ns.Audit()end end},
            {"Measure FPS / addons",function()ns.Performance()end},
            {"Refresh status",ns.ShowProgress},
            {"Weapon results",function()ns.ShowResults()end},
            {"Farming checklist",function()ns.ShowFarm()end},
            {"Compare last item",function()
                if not ns.lastInspectedItem then print("Ret Sim: hover an item first.");return end
                if ns.QueueItems(ns.lastInspectedItem)>0 then ns.ReloadSimResults(true) end
            end},
        }
        for i,action in ipairs(actions) do
            local button=CreateFrame("Button",nil,window,"UIPanelButtonTemplate")
            button:SetPoint("TOPLEFT",22+((i-1)%3)*179,-247-math.floor((i-1)/3)*35);button:SetSize(168,27);button:SetText(action[1]);button:SetScript("OnClick",action[2]);button:Hide()
            window.extra[#window.extra+1]=button
        end
        local note=window:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall");note:SetPoint("BOTTOMLEFT",22,22);note:SetWidth(526);note:SetJustifyH("LEFT")
        note:SetText("Two clicks: Update sims, then Load results when the desktop helper is ready. Reloads wait for your click outside combat. Profiles and scoring checks are automatic.")
        if UISpecialFrames then table.insert(UISpecialFrames,"GuildSimBetaProgressFrame") end
    end
    local step,title,detail,action=ns.ProgressState()
    window.title:SetText(title);window.bar:SetValue(step==3 and 2 or (action=="capture" and 0 or 1))
    window.count:SetText(step==3 and "Up to date" or "1. Update sims   >   2. Load results");window.detail:SetText(detail)
    window.primary:SetText(({capture="Update sims",load="Load results — reload",save="Save capture — reload",apply="Apply loaded weights"})[action] or "Update sims")
    if step==3 and GuildSimBetaDB and GuildSimBetaDB.progressRequests then GuildSimBetaDB.progressRequests[UnitGUID("player")]=nil end
    window:Show()
end

function ns.CaptureProgress(sourceExport)
    GuildSimBetaDB=GuildSimBetaDB or {};GuildSimBetaDB.progressRequests=GuildSimBetaDB.progressRequests or {}
    GuildSimBetaDB.progressRequests[UnitGUID("player")]=sourceExport and {sourceExport=sourceExport,inventorySignature=ns.QuickInventorySignature and ns.QuickInventorySignature()} or true
    capturedThisSession=true
    ns.ShowProgress()
end

local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("ADDON_ACTION_BLOCKED");events:RegisterEvent("ADDON_ACTION_FORBIDDEN")
events:SetScript("OnEvent",function(_,event,addon)
    if event=="ADDON_ACTION_BLOCKED" or event=="ADDON_ACTION_FORBIDDEN" then
        if addon=="GuildSimBeta" then reloadHelp("WoW blocked the addon reload call.") end
        return
    end
    C_Timer.After(6,function()
        if GuildSimBetaDB and GuildSimBetaDB.progressRequests and GuildSimBetaDB.progressRequests[UnitGUID("player")] then ns.ShowProgress() end
    end)
end)
