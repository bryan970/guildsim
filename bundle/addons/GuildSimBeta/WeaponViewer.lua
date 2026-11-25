if select(2,UnitClass("player"))~="PALADIN" then return end
local _, ns = ...
local function say(text) print("|cffead36cRet Sim:|r " .. text) end
ns.weaponContext = "equipped"
local checkedSource, checkedLive, checkedMaskEqual, liveValid
local function exporter()
    local lib = LibStub and LibStub("AceAddon-3.0", true)
    return lib and lib:GetAddon("WowSimsExporter", true)
end
-- Background freshness checks are not a request for enchant reminders.
-- Use the exporter's own warning option only for this synchronous call, then
-- restore it even on error; explicit /wse exports retain their normal warnings.
function ns.ReadExport(addon,save)
    if not addon or not addon.BuildExport then return false end
    local global=addon.db and addon.db.global
    local options=global and global.exportOptions
    if global and type(options)~="table" then options={};global.exportOptions=options end
    local previous=options and options.warnMissing
    if options then options.warnMissing=false end
    local ok,data=pcall(addon.BuildExport,addon,false,not save)
    if options then options.warnMissing=previous end
    return ok,data
end
local function liveExport(save)
    local addon = exporter()
    if not addon or not addon.BuildExport then return end
    local ok, data = ns.ReadExport(addon,save)
    if ok then return data end
end
local function currentLive()
    if not liveValid then checkedLive=liveExport(false);liveValid=checkedLive~=nil end
    return checkedLive
end
ns.LiveSimExport=currentLive
local function gearElement(text,wanted)
    local gear=text:find('"gear"%s*:%s*{')
    local _,opening=text:find('"items"%s*:%s*%[',gear or 1)
    if not opening then return end
    local depth,index,first,quoted,escaped=1,1,opening+1,false,false
    for i=opening+1,#text do
        local ch=text:sub(i,i)
        if quoted then
            if escaped then escaped=false elseif ch=="\\" then escaped=true elseif ch=='"' then quoted=false end
        elseif ch=='"' then quoted=true
        elseif ch=='{' or ch=='[' then depth=depth+1
        elseif ch=='}' or ch==']' then
            depth=depth-1
            if depth==0 then if index==wanted then return first,i-1 end;return end
        elseif ch==',' and depth==1 then
            if index==wanted then return first,i-1 end
            index=index+1;first=i+1
        end
    end
end
function ns.CombatExport(text)
    if type(text)~="string" then return nil end
    text=text:gsub('("professions"%s*:%s*)(%b[])',function(prefix,body)
        return prefix..body:gsub('("level"%s*:%s*)%d+',function(key)return key..'0'end)
    end)
    for _,key in ipairs({"version","realm","unit"}) do
        text=text:gsub('("'..key..'"%s*:%s*)"[^"]*"',function(prefix)return prefix..'""'end)
    end
    local payload=ns.payload or ns.weaponResults or {}
    local pins=payload.combatTrinkets or (ns.weaponResults and ns.weaponResults.combatTrinkets) or {}
    local mounts={};for _,id in ipairs(payload.mountTrinketIds or {11122}) do if id~=19812 then mounts[id]=true end end
    for _,slot in ipairs({13,14}) do
        local first,last=gearElement(text,slot)
        local equipped=first and tonumber(text:sub(first,last):match('"id"%s*:%s*(%d+)'))
        local pin=pins[tostring(slot)]
        if equipped and mounts[equipped] and pin and pin.id then
            local fields={}
            for _,key in ipairs({"enchant","id","randomSuffix"}) do
                if pin[key] and pin[key]~=0 then fields[#fields+1]='"'..key..'":'..pin[key] end
            end
            text=text:sub(1,first-1)..'{'..table.concat(fields,',')..'}'..text:sub(last+1)
        end
    end
    return text
end
function ns.SameCombatExport(a,b)
    return type(a)=="string" and type(b)=="string" and ns.CombatExport(a)==ns.CombatExport(b)
end
function ns.CatalogExport(text,payload)
    if type(text)~="string" then return nil end
    if payload and payload.referenceTrinkets then
        for _,slot in ipairs({14,13}) do
            local first,last=gearElement(text,slot)
            if not first then return nil end
            text=text:sub(1,first-1)..'{}'..text:sub(last+1)
        end
    end
    return ns.CombatExport(text)
end
function ns.SameCatalogExport(a,b,payload)
    local first=ns.CatalogExport(a,payload)
    return first~=nil and first==ns.CatalogExport(b,payload)
end
function ns.ProjectionWeightsFresh(name)
    local p=ns.payload
    if p and ns.engineCommit and (not p.wowsims or p.wowsims.upstream_commit~=ns.engineCommit) then return false,"Simulation engine updated. Update sims to refresh these weights." end
    if not p or (p.context~="equipped" and p.mode~="current") then return true end
    local targetView=GuildSimBetaDB and GuildSimBetaDB.weightView=="target"
    if name and name:find("Planning",1,true) then
        if targetView then return true end
        return false,"The old final-target profile is selected. /guildsim update switches to current-gear weights."
    end
    if not name and targetView then return true end
    if UnitGUID("player")~=p.guid then return false,"Weights belong to another character." end
    if time()-p.generated>7*86400 then return false,"Current-gear weights are over a week old." end
    if not ns.SameCombatExport(currentLive(),p.sourceExport) then return false,"Combat gear or talents changed. Use Update sims in /guildsim; riding trinkets and profession skill-ups are ignored." end
    return true
end
-- Compare exports while masking only equipment array element 15. This is a
-- structural string scan, not a regex over nested JSON or an executable parser.
local function maskWeapon(text)
    if type(text) ~= "string" then return nil end
    local gear=text:find('"gear"%s*:%s*{')
    if not gear then return nil end
    local _, opening=text:find('"items"%s*:%s*%[',gear)
    if not opening then return nil end
    local depth, element, first, quoted, escaped = 1, 1, opening+1, false, false
    for i=opening+1,#text do
        local ch=text:sub(i,i)
        if quoted then
            if escaped then escaped=false elseif ch=="\\" then escaped=true elseif ch=='"' then quoted=false end
        elseif ch=='"' then quoted=true
        elseif ch=='{' or ch=='[' then depth=depth+1
        elseif ch=='}' or ch==']' then
            depth=depth-1
            if depth==0 then
                if element==15 then return text:sub(1,first-1)..'{}'..text:sub(i) end
                return nil
            end
        elseif ch==',' and depth==1 then
            if element==15 then return text:sub(1,first-1)..'{}'..text:sub(i) end
            element=element+1;first=i+1
        end
    end
end
ns.MaskWeaponExport=maskWeapon
local function itemParts(link)
    local text = tostring(link or "")
    local body = text:match("item:([%-%d:]+)")
    if not body then return tonumber(text), 0, 0 end
    local fields = {}
    for value in (body .. ":"):gmatch("(.-):") do fields[#fields + 1] = value end
    return tonumber(fields[1]), tonumber(fields[7]) or 0, tonumber(fields[2]) or 0
end
function ns.WeaponData(contextKey)
    local result = ns.weaponResults
    if not result or UnitGUID("player") ~= result.guid then return nil, "No full weapon results for this character yet." end
    if ns.engineCommit and result.engineCommit~=ns.engineCommit then return nil,"Simulation engine updated. Click Update sims, reload, then load results when the helper is ready." end
    if time() - result.generated > 7 * 86400 then return nil, "Weapon results are over a week old. Capture weapons and rerun the helper." end
    local context
    for _, c in ipairs(result.contexts) do if c.key == (contextKey or ns.weaponContext) then context = c end end
    if not context then return nil, "Comparison context is unavailable." end
    if context.key == "equipped" then
        if checkedSource ~= result.sourceExport then
            checkedSource=result.sourceExport;checkedLive=currentLive();checkedMaskEqual=nil
            if not ns.SameCatalogExport(checkedLive,result.sourceExport,result) then
                local sourceMask=maskWeapon(ns.CatalogExport(result.sourceExport,result))
                checkedMaskEqual=sourceMask and sourceMask==maskWeapon(ns.CatalogExport(checkedLive,result))
            end
        end
        local onlyWeaponChanged=checkedMaskEqual
        if not ns.SameCatalogExport(checkedLive,result.sourceExport,result) and not onlyWeaponChanged then
            return nil, "Exported gear/level/talents changed. /guildsim weapons, /reload, wait for the helper, then /reload. The final-target view is independent of worn gear."
        end
        if not ns.SameCatalogExport(checkedLive,result.sourceExport,result) then
            local link=GetInventoryItemLink and GetInventoryItemLink("player",16)
            local id,suffix,enchant=itemParts(link)
            local base
            for _, row in ipairs(context.weapons) do if row.id==id and (row.randomSuffix or 0)==suffix then base=row end end
            if not base or enchant~=context.enchant then return nil,"Equipped weapon or enchant differs from the simulated options. /guildsim weapons, /reload; wait for the helper, then /reload." end
            local rebased={}
            for k,v in pairs(context) do rebased[k]=v end
            rebased.baselineId=id;rebased.baselineSuffix=suffix;rebased.baselineName=base.name;rebased.baselineDps=base.dps;rebased.secondsOom=base.secondsOom
            rebased.weapons={}
            for _, row in ipairs(context.weapons) do
                local r={};for k,v in pairs(row)do r[k]=v end
                r.delta=r.dps-base.dps;r.percent=100*(r.dps/base.dps-1);r.baseline=r.id==id and (r.randomSuffix or 0)==suffix
                rebased.weapons[#rebased.weapons+1]=r
            end
            context=rebased
        end
    end
    return context, result
end
function ns.WeaponForLink(link,contextKey)
    contextKey=contextKey or "equipped" -- tooltips never follow the planning-window tab
    local body=tostring(link or ""):match("item:([%-%d:]+)")
    if body then
        local fields={};for value in (body..":"):gmatch("(.-):") do fields[#fields+1]=value end
        local unsupported=(tonumber(fields[13]) or 0)>0
        for i=3,6 do if (tonumber(fields[i]) or 0)~=0 then unsupported=true end end
        if unsupported then return nil,nil,nil,"This bonus-list or gem variant is not represented by the simulator export." end
    end
    local id, suffix = itemParts(link)
    local context, result = ns.WeaponData(contextKey)
    if not context then return nil, nil, nil, result end
    for _, row in ipairs(context.weapons) do
        if row.id == id and (row.randomSuffix or 0) == suffix then
            local displayed=tostring(link):match("|h%[([^%]]+)%]|h")
            if suffix==0 and displayed and displayed~=row.name then return nil,nil,nil,"The displayed weapon variant differs from the simulated item." end
            return row, context, result
        end
    end
    if result.scope=="quick" then
        return nil,nil,nil,"Not in current quick weapon comparisons. /guildsim > More options > Compare last item adds a focused comparison."
    end
end
function ns.WeaponComparison(link)
    if ns.ItemEligibility then
        local usable,why=ns.ItemEligibility(link)
        if usable==false then return nil,why end
    end
    local row,context,result,why=ns.WeaponForLink(link,"equipped")
    if not row and ns.weaponResults and ns.weaponResults.catalogMode then
        local id,suffix=itemParts(link)
        for _,c in ipairs(ns.weaponResults.contexts or {}) do
            if c.key=="equipped" then
                for _,error in ipairs(c.errors or {}) do
                    if error.id==id and (error.randomSuffix==nil or error.randomSuffix==suffix) then return nil,error.reason end
                end
            end
        end
        return nil,why or "No matching full-catalog result for this variant. Add a focused comparison in /guildsim."
    end
    if not row then return nil,why or "Weapon queued for full simulation. Click Update sims in /guildsim, then Load results when the helper is ready." end
    local provisional=row.provisionalProc
    for _, candidate in ipairs(context.weapons) do if candidate.baseline and candidate.provisionalProc then provisional=true end end
    local missing,conditions
    if ns.EffectCoverage then missing,conditions=ns.EffectCoverage(result,row.id,context.baselineId) end
    return {percent=row.percent,delta=row.delta,dps=row.dps,baselineDps=context.baselineDps,
        baselineName=context.baselineName,baselineId=context.baselineId,provisional=provisional or missing~=nil,missingEffects=missing,conditions=conditions,
        exportedLevel=result.exportedLevel,uncertain=row.uncertain,pairedError95=row.pairedError95,backend=row.backend,comparisonLabel=result.comparisonLabel}
end
GuildSimBetaWeapons={Compare=ns.WeaponComparison,WeightsFresh=ns.ProjectionWeightsFresh}
GuildSimBetaWeapons.Catalog=function()return ns.WeaponData("equipped")end
function ns.SavedWeaponComparison(link)
    local id,suffix=itemParts(link)
    for index=1,2 do
    local p=index==1 and ns.weaponResults or ns.weaponSnapshot
    if p and UnitGUID("player")==p.guid then
    for _,context in ipairs(p.contexts or {}) do
        if context.key=="equipped" then
            for _,row in ipairs(context.weapons or {}) do
                if row.id==id and (row.randomSuffix or 0)==suffix then
                    return {delta=row.delta,percent=row.percent,baselineName=context.baselineName,generated=p.generated}
                end
            end
        end
    end
    end
    end
end
GuildSimBetaWeapons.Saved=ns.SavedWeaponComparison
local freshness=CreateFrame("Frame")
for _, event in ipairs({"PLAYER_EQUIPMENT_CHANGED","UNIT_INVENTORY_CHANGED","PLAYER_LEVEL_UP","PLAYER_TALENT_UPDATE","SKILL_LINES_CHANGED","PLAYER_ENTERING_WORLD"}) do
    pcall(freshness.RegisterEvent,freshness,event)
end
function ns.InvalidateSimFreshness()checkedSource=nil;checkedLive=nil;checkedMaskEqual=nil;liveValid=nil end
freshness:SetScript("OnEvent",function(_,event,unit)
    if event=="UNIT_INVENTORY_CHANGED" and unit~="player" then return end
    ns.InvalidateSimFreshness()
end)
local function queue(link)
    local id, suffix = itemParts(link)
    if not id then return false end
    local info = (C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    if not info then return false end
    local lookup = tonumber(link) or link
    local _, _, _, loc, _,classId,subclass = info(lookup)
    if loc ~= "INVTYPE_2HWEAPON" then return false end
    if classId and (classId~=2 or not ({[1]=true,[5]=true,[6]=true,[8]=true})[subclass]) then return false end
    local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
    local name = getInfo and getInfo(lookup)
    -- Forever bonus-list variants cannot safely be guessed from an item ID.
    GuildSimBetaDB = GuildSimBetaDB or {}
    GuildSimBetaDB.weaponQueue = GuildSimBetaDB.weaponQueue or {}
    local guid = UnitGUID("player")
    GuildSimBetaDB.weaponQueue[guid] = GuildSimBetaDB.weaponQueue[guid] or {}
    GuildSimBetaDB.weaponQueue[guid][id .. ":" .. suffix] = {id=id, randomSuffix=suffix, name=name}
    return true
end
function ns.QueueWeaponLink(link)
    local id,suffix=itemParts(link)
    if not id then return false end
    if ns.weaponResults and ns.weaponResults.catalogMode then
        for _,context in ipairs(ns.weaponResults.contexts or {}) do
            for _,row in ipairs(context.weapons or {}) do
                if row.id==id and (row.randomSuffix or 0)==suffix then return false end
            end
        end
    end
    local queues=GuildSimBetaDB and GuildSimBetaDB.weaponQueue
    local queueForPlayer=queues and queues[UnitGUID("player")]
    local old=queueForPlayer and queueForPlayer[id..":"..suffix]
    local oldName=old and old.name
    if not queue(link) then return false end
    local row=GuildSimBetaDB.weaponQueue[UnitGUID("player")][id..":"..suffix]
    return not old or row.name~=oldName
end
function ns.QueueWeapons(input)
    local count = 0
    if input and input ~= "" then
        if queue(input) then count = 1 else say("Use a supported two-handed weapon link or ID. Unreadable random-stat variants are not guessed."); return end
    else
        if queue(GetInventoryItemLink("player",16)) then count = count + 1 end
        if C_Container then
            for bag = 0, NUM_BAG_SLOTS or 4 do
                for slot = 1, C_Container.GetContainerNumSlots(bag) do
                    local link = C_Container.GetContainerItemLink(bag,slot)
                    if link and queue(link) then count = count + 1 end
                end
            end
        end
    end
    local captured=liveExport(true)
    if not captured then say("Could not capture your character export. Try again when the exporter is ready."); return end
    ns.InvalidateSimFreshness()
    if ns.CaptureProgress then ns.CaptureProgress(captured) end
    if ns.weaponResults and ns.weaponResults.catalogMode then
        say("Captured gear and bags for a quick update. Save the capture, then load results when ready. Full catalog runs are separate in the desktop monitor.")
    else say("Captured " .. count .. " weapon copies and your character. /reload to save, wait for the local helper, then /reload and /guildsim results.") end
    return true
end
function ns.ClearWeapons()
    GuildSimBetaDB = GuildSimBetaDB or {}
    if GuildSimBetaDB.weaponQueue then GuildSimBetaDB.weaponQueue[UnitGUID("player")] = nil end
    say("Weapon queue cleared. /reload to save. The standard comparison weapons remain available.")
end
function ns.WeaponSummary(context,result)
    local text = {context.name, "", string.format("Baseline: %s — %.2f simulated DPS; %.1f seconds out of mana",
        context.baselineName,context.baselineDps,context.secondsOom),
        string.format("Level 60 • %ds • boss level %d • %s%d iterations per weapon",result.duration,result.targetLevel,result.catalogMode and "up to " or "",result.iterations),
        "Each row changes ONLY the weapon. The baseline weapon's enchant is applied to every candidate.",
        "No hit-cap rebalance or other gear swaps. Speed, min/max damage and implemented effects are simulated.",
        "Close results may be statistical ties. Provisional proc rates are marked. These are model predictions, not live DPS measurements.", ""}
    if result.catalogMode then
        text[#text+1]=result.scope=="quick" and string.format("Quick pool: %d weapons / %d variants, plus matching catalog snapshot results when available.",result.catalogWeapons,result.catalogVariants)
            or string.format("Complete catalog: %d weapons / %d variants. Every variant gets %d full-combat iterations; upgrades, near-baseline choices and the top 25 get %d.",result.catalogWeapons,result.catalogVariants,result.screenIterations,result.iterations)
        text[#text+1]=string.format("Showing the top %d of %d successful results. Every simulated weapon is available in tooltips.",math.min(80,#context.weapons),#context.weapons)
    end
    for index, row in ipairs(context.weapons) do
        if result.catalogMode and index>80 then break end
        text[#text+1] = string.format("%s%s: %.2f DPS   %+.2f DPS (%+.2f%%)%s",
            row.baseline and "[baseline] " or "",row.name,row.dps,row.delta,row.percent,
            row.provisionalProc and "  [provisional proc]" or "")
        if row.sourceUnverified then text[#text+1]="    Acquisition source is unverified; this is not a confirmed farming target." end
        text[#text+1] = string.format("    %.2fs • %.0f–%.0f base damage • mean DPS error about ±%.2f • %.1fs OOM • %d iterations",
            row.speed,row.damageMin,row.damageMax,row.meanError95,row.secondsOom,row.iterations or result.iterations)
    end
    if #context.errors > 0 then
        text[#text+1] = "\nNot simulated:"
        for _, error in ipairs(context.errors) do text[#text+1] = tostring(error.id) .. ": " .. error.reason end
    end
    if context.key=="equipped" and result.comparisonLabel then text[#text+1]=result.comparisonLabel..". Catalog DPS uses this pair rather than your currently worn trinkets." end
    text[#text+1] = "\nRaid assumptions:"
    for group, names in pairs(result.raidAssumptions or {}) do text[#text+1] = group .. ": " .. table.concat(names, ", ") end
    text[#text+1] = result.catalogMode and "\nThe full compatible level-60 two-handed catalog refreshes automatically for changed gear, talents, raid settings or engine data. Unchanged combat inputs reuse cached results. No per-weapon capture is needed. Catalog presence does not verify a live acquisition source."
        or "\nMore weapons: /guildsim weapons captures equipped/bag weapons. /guildsim weapon ITEMLINK_OR_ID queues a specific weapon. Then /reload; wait for the helper; /reload again."
    return table.concat(text,"\n")
end
local window
function ns.ShowResults()
    if not window then
        window=CreateFrame("Frame","GuildSimBetaResultsFrame",UIParent,"BackdropTemplate")
        window:SetSize(1040,720);window:SetPoint("CENTER");window:SetFrameStrata("DIALOG")
        window:SetBackdrop({bgFile="Interface\\DialogFrame\\UI-DialogBox-Background",edgeFile="Interface\\DialogFrame\\UI-DialogBox-Border",tile=true,tileSize=32,edgeSize=24,insets={left=6,right=6,top=6,bottom=6}})
        window:EnableMouse(true);window:SetMovable(true);window:RegisterForDrag("LeftButton")
        window:SetScript("OnDragStart",window.StartMoving);window:SetScript("OnDragStop",window.StopMovingOrSizing)
        local close=CreateFrame("Button",nil,window,"UIPanelCloseButton");close:SetPoint("TOPRIGHT",-5,-5)
        local title=window:CreateFontString(nil,"OVERLAY","GameFontNormalLarge");title:SetPoint("TOPLEFT",24,-24);title:SetText("Ret Sim — full weapon comparisons")
        local controls=CreateFrame("Button",nil,window,"UIPanelButtonTemplate");controls:SetSize(150,25);controls:SetPoint("TOPRIGHT",-46,-55);controls:SetText("Sim controls");controls:SetScript("OnClick",function()ns.ShowProgress()end)
        for i, data in ipairs({{"equipped","Exported gear at level 60"},{"target","Final planning set"}}) do
            local key=data[1]
            local button=CreateFrame("Button",nil,window,"UIPanelButtonTemplate");button:SetSize(245,25);button:SetPoint("TOPLEFT",24+(i-1)*260,-55);button:SetText(data[2])
            button:SetScript("OnClick",function()ns.weaponContext=key;ns.ShowResults()end)
        end
        local scroll=CreateFrame("ScrollFrame",nil,window,"UIPanelScrollFrameTemplate");scroll:SetPoint("TOPLEFT",24,-100);scroll:SetPoint("BOTTOMRIGHT",-46,32)
        local content=CreateFrame("Frame",nil,scroll);content:SetSize(950,1800);scroll:SetScrollChild(content)
        window.text=content:CreateFontString(nil,"OVERLAY","GameFontHighlight");window.text:SetPoint("TOPLEFT");window.text:SetWidth(940);window.text:SetJustifyH("LEFT")
        window.content=content
        if UISpecialFrames then table.insert(UISpecialFrames,"GuildSimBetaResultsFrame") end
    end
    local context,result=ns.WeaponData()
    window.text:SetText(context and ns.WeaponSummary(context,result) or result)
    window.content:SetHeight(math.max(100,window.text:GetStringHeight()+30));window:Show()
end
local function tooltip(tip)
    if not tip or not tip.GetItem then return end
    local _,link=tip:GetItem()
    if not link then return end
    local info=(C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    if not info then return end
    local _,_,_,location=info(link)
    if location~="INVTYPE_2HWEAPON" then return end
    if ns.ItemEligibility and ns.ItemEligibility(link)==false then return end
    local fresh,problem=ns.ProjectionWeightsFresh()
    if not fresh then
        tip:AddLine("Current-gear sim weights need refresh",1,0.75,0.3)
        tip:AddLine(problem,1,0.85,0.6,true)
    end
    local row,context,result,why=ns.WeaponForLink(link)
    if not row then
        if why then
            tip:AddLine("Full weapon sim needs refresh",1,0.75,0.3)
            tip:AddLine(why,1,0.85,0.6,true)
            local saved=ns.SavedWeaponComparison(link)
            if saved then
                tip:AddLine(string.format("Previous combat setup: %+.2f DPS (%+.2f%%) vs %s",saved.delta,saved.percent,saved.baselineName),0.75,0.75,0.75,true)
                if date then tip:AddLine("Saved "..date("%m/%d %H:%M",saved.generated),0.65,0.65,0.65) end
                tip:AddLine("Out of date; upgrade arrows wait for current results.",1,0.75,0.3,true)
            end
        end
        return
    end
    tip:AddLine("Full weapon sim — level 60",0.3,0.85,1)
    if result.comparisonLabel then tip:AddLine(result.comparisonLabel.."; reference catalog DPS.",0.7,0.85,1,true) end
    tip:AddLine(string.format("%+.2f DPS (%+.2f%%) vs %s",row.delta,row.percent,context.baselineName),0.7,0.9,1,true)
    tip:AddLine(context.key=="target" and "Final planning set" or (result.exportedLevel<60 and "Exported gear projected to 60" or "Exported level-60 gear"),0.8,0.8,0.8,true)
    if row.provisionalProc then tip:AddLine("Weapon proc rate is provisional.",1,0.75,0.3,true) end
    if ns.EffectCoverage then
        local missing,conditions=ns.EffectCoverage(result,row.id,context.baselineId)
        if missing then tip:AddLine("Partial model; no upgrade arrow. WoWSims missing: "..missing,1,0.75,0.3,true) end
        if conditions then tip:AddLine(conditions,0.8,0.8,0.8,true) end
    end
    if row.pairedError95 then tip:AddLine(string.format("WoWSims bulk: swap DPS error ±%.2f (95%%)",row.pairedError95),0.7,0.85,1,true) end
    if row.uncertain then tip:AddLine("Difference is within estimated simulation sampling error.",1,0.75,0.3,true) end
    tip:AddLine("/guildsim results — setup and full comparisons",0.8,0.8,0.8)
end
if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item,function(t)pcall(tooltip,t)end)
elseif GameTooltip and GameTooltip.HookScript then
    GameTooltip:HookScript("OnTooltipSetItem",function(t)pcall(tooltip,t)end)
end
