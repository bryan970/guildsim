if select(2,UnitClass("player"))~="PALADIN" then return end
local _, ns = ...
ns.SameCombatExport=ns.SameCombatExport or function(a,b)return type(a)=="string" and a==b end
local locations={INVTYPE_HEAD=true,INVTYPE_NECK=true,INVTYPE_SHOULDER=true,INVTYPE_CLOAK=true,
    INVTYPE_CHEST=true,INVTYPE_ROBE=true,INVTYPE_WRIST=true,INVTYPE_HAND=true,INVTYPE_WAIST=true,
    INVTYPE_LEGS=true,INVTYPE_FEET=true,INVTYPE_FINGER=true,INVTYPE_TRINKET=true,INVTYPE_RELIC=true}
local dirty, scheduled, notice, noticeShown
local function parts(link)
    local text=tostring(link or "")
    local body=text:match("item:([%-%d:]+)")
    if not body then return tonumber(text),0,0,false end
    local fields={};for v in (body..":"):gmatch("(.-):") do fields[#fields+1]=v end
    local unsupported=(tonumber(fields[13]) or 0)>0
    for i=3,6 do if (tonumber(fields[i]) or 0)~=0 then unsupported=true end end
    return tonumber(fields[1]),tonumber(fields[7]) or 0,tonumber(fields[2]) or 0,unsupported
end
local function key(id,suffix,enchant)return id..":"..suffix..":"..enchant end
function ns.ItemEligibility(link)
    local id=parts(link)
    if not id then return nil end
    if UnitClass and select(2,UnitClass("player"))~="PALADIN" then return nil end
    local current=ns.itemResults
    local restrictions=current and current.classRestrictions
    if restrictions and (restrictions[id] or restrictions[tostring(id)]) then
        return false,"Cannot equip: this item is restricted to other classes.","ineligible"
    end
    for _,p in pairs({current=current,snapshot=ns.itemSnapshot}) do
        local why=p.errors and p.errors[key(id,0,0)]
        if why=="Not usable by a Paladin" then return false,"Cannot equip: this item is restricted to other classes.","ineligible" end
    end
    -- The game's tooltip also covers class restrictions absent from the sim database.
    if C_TooltipInfo and C_TooltipInfo.GetHyperlink and UnitClass then
        local query=type(link)=="number" and ("item:"..link) or link
        local ok,data=pcall(C_TooltipInfo.GetHyperlink,query)
        if not ok then data=nil end
        local class=UnitClass("player")
        for _,line in ipairs(data and data.lines or {}) do
            local text=(line.leftText or ""):gsub("|c%x%x%x%x%x%x%x%x",""):gsub("|r","")
            local allowed=text:match("^Classes:%s*(.+)")
            if allowed then
                local found=false
                for token in allowed:gmatch("[^,]+") do if token:match("^%s*(.-)%s*$")==class then found=true end end
                if not found then return false,"Cannot equip: class restriction ("..allowed..").","ineligible" end
            end
        end
    end
    local info=(C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    if info then
        local _,_,_,_,_,itemClass,subclass=info(link)
        if itemClass==2 and subclass and not ({[0]=true,[1]=true,[4]=true,[5]=true,[6]=true,[7]=true,[8]=true,[20]=true})[subclass] then
            return false,"Cannot equip: Paladins cannot use this weapon type.","ineligible"
        end
    end
    return true
end
function ns.IsItemSimSupported(link)
    local info=(C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    if not info then return false end
    local _,_,_,loc=info(tonumber(link) or link)
    return locations[loc] or false
end
function ns.QueueItem(link)
    if ns.payload and ns.payload.guid~=UnitGUID("player") then return false end
    local id,suffix,enchant,unsupported=parts(link)
    if not id then return false end
    if ns.itemResults and ns.itemResults.catalogMode then return false end
    if not ns.IsItemSimSupported(link) then
        if unsupported or not ns.QueueWeaponLink or not ns.QueueWeaponLink(link) then return false end
        local known
        for _,context in ipairs(ns.weaponResults and ns.weaponResults.contexts or {}) do
            if context.key=="equipped" then
                for _,row in ipairs(context.weapons or {}) do
                    if row.id==id and (row.randomSuffix or 0)==suffix then known=true end
                end
                for _,row in ipairs(context.errors or {}) do
                    if row.id==id then known=true end
                end
            end
        end
        if not known then dirty=true end
        return true
    end
    GuildSimBetaDB=GuildSimBetaDB or {};local db=GuildSimBetaDB
    db.itemQueue=db.itemQueue or {};local guid=UnitGUID("player")
    db.itemQueue[guid]=db.itemQueue[guid] or {};local queue=db.itemQueue[guid]
    local k=key(id,suffix,enchant)
    local getInfo=(C_Item and C_Item.GetItemInfo) or GetItemInfo
    local name=getInfo and getInfo(tonumber(link) or link)
    local row=queue[k]
    if row and row.name==name and not not row.unsupportedVariant==not not unsupported then return false end
    queue[k]={id=id,randomSuffix=suffix,enchant=enchant,name=name,unsupportedVariant=unsupported,lastSeen=time()}
    -- The desktop queue is bounded; retain the most recently encountered items.
    local count,oldest,oldTime=0,nil,math.huge
    for candidate,v in pairs(queue) do
        count=count+1;if (v.lastSeen or 0)<oldTime then oldest=candidate;oldTime=v.lastSeen or 0 end
    end
    if count>160 and oldest then queue[oldest]=nil end
    local result=ns.itemResults
    local known=result and result.guid==guid and time()-result.generated<=7*86400
        and ((result.items and result.items[k]) or (result.errors and result.errors[k]))
    if not known then dirty=true end
    return true
end
function ns.QueueItems(input)
    local count=0
    if input then
        local usable,why=ns.ItemEligibility(input)
        if usable==false then print("Ret Sim: "..why);return 0 end
        local id,suffix,enchant,unsupported=parts(input)
        if not id then return 0 end
        GuildSimBetaDB=GuildSimBetaDB or {};GuildSimBetaDB.manualItems=GuildSimBetaDB.manualItems or {}
        local guid=UnitGUID("player");GuildSimBetaDB.manualItems[guid]=GuildSimBetaDB.manualItems[guid] or {}
        local pins=GuildSimBetaDB.manualItems[guid]
        pins[key(id,suffix,enchant)]={id=id,randomSuffix=suffix,enchant=enchant,unsupportedVariant=unsupported,lastSeen=time()}
        local size,oldest,oldTime=0,nil,math.huge
        for k,row in pairs(pins) do size=size+1;if (row.lastSeen or 0)<oldTime then oldest=k;oldTime=row.lastSeen or 0 end end
        if size>20 and oldest then pins[oldest]=nil end
        dirty=true;return 1
    end
    GuildSimBetaDB=GuildSimBetaDB or {};GuildSimBetaDB.quickItems=GuildSimBetaDB.quickItems or {}
    local owned={};GuildSimBetaDB.quickItems[UnitGUID("player")]=owned
    local function capture(link)
        local id,suffix,enchant,unsupported=parts(link)
        if not id then return end
        if ns.ItemEligibility(link)==false then return end
        for _,utility in ipairs((ns.payload and ns.payload.mountTrinketIds) or {11122,12846}) do if utility~=19812 and id==utility then return end end
        if ns.RememberTrinket then ns.RememberTrinket(link) end
        local info=(C_Item and C_Item.GetItemInfo) or GetItemInfo
        owned[key(id,suffix,enchant)]={id=id,randomSuffix=suffix,enchant=enchant,unsupportedVariant=unsupported,name=info and info(link)}
        local p=ns.itemResults
        if p and p.scope=="quick" and ns.IsItemSimSupported(link) and not p.items[key(id,suffix,enchant)] and not (p.errors and p.errors[key(id,suffix,enchant)]) then dirty=true end
    end
    for slot=1,18 do
        local link=GetInventoryItemLink and GetInventoryItemLink("player",slot)
        if link then capture(link);if ns.QueueItem(link) then count=count+1 end end
    end
    if C_Container then
        for bag=0,NUM_BAG_SLOTS or 4 do
            for slot=1,C_Container.GetContainerNumSlots(bag) do
                local link=C_Container.GetContainerItemLink(bag,slot)
                if link then capture(link);if ns.QueueItem(link) then count=count+1 end end
            end
        end
    end
    return count
end
function ns.ItemComparisonsFresh()
    local p=ns.itemResults
    if not p or p.guid~=UnitGUID("player") then return false,"Item sims have not been loaded for this character." end
    if time()-p.generated>7*86400 then return false,"Item simulations need refreshing." end
    if not ns.LiveSimExport or not (ns.SameCatalogExport or ns.SameCombatExport)(ns.LiveSimExport(),p.sourceExport,p) then return false,"Your combat gear or talents changed. Click Update sims in /guildsim." end
    return true
end
function ns.ItemsCovered()
    if ns.itemResults and ns.itemResults.scope=="quick" and dirty then return false end
    if ns.itemResults and ns.itemResults.catalogMode then return ns.itemResults.complete and ns.ItemComparisonsFresh() end
    if dirty then return false end
    local p=ns.itemResults
    if not p then return false end
    local queue=GuildSimBetaDB and GuildSimBetaDB.itemQueue
    for k in pairs(queue and queue[UnitGUID("player")] or {}) do
        if not p.items[k] and not (p.errors and p.errors[k]) then return false end
    end
    return ns.ItemComparisonsFresh()
end
function ns.ItemCapturePending()return dirty end
function ns.QueueInspectedItem(link)
    local p=ns.itemResults
    if not (p and p.scope=="quick") then return ns.QueueItem(link) end
    if p.guid~=UnitGUID("player") or ns.ItemEligibility(link)==false then return false end
    local id,suffix,enchant,unsupported=parts(link)
    if not id or unsupported then return false end
    local info=(C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    local location
    if info then local _,_,_,value=info(link);location=value end
    if not (locations[location] or location=="INVTYPE_2HWEAPON") then return false end
    local k=key(id,suffix,enchant)
    if p.items[k] or (p.errors and p.errors[k]) then return false end
    GuildSimBetaDB=GuildSimBetaDB or {};local db=GuildSimBetaDB
    db.inspectedItems=db.inspectedItems or {};local guid=UnitGUID("player")
    db.inspectedItems[guid]=db.inspectedItems[guid] or {};local queue=db.inspectedItems[guid]
    if queue[k] then return false end
    db.inspectionSequence=(db.inspectionSequence or 0)+1
    queue[k]={id=id,randomSuffix=suffix,enchant=enchant,lastSeen=time(),sequence=db.inspectionSequence}
    local size,oldest,oldTime,oldSequence=0,nil,math.huge,math.huge
    for candidate,row in pairs(queue) do
        size=size+1
        if row.lastSeen<oldTime or (row.lastSeen==oldTime and (row.sequence or 0)<oldSequence) then
            oldest=candidate;oldTime=row.lastSeen;oldSequence=row.sequence or 0
        end
    end
    if size>20 and oldest then queue[oldest]=nil end
    dirty=true;return true
end
function ns.QuickInventorySignature()
    local db=GuildSimBetaDB or {};local guid=UnitGUID("player");local keys={}
    local info=(C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    for k,row in pairs(db.quickItems and db.quickItems[guid] or {}) do
        local loc
        if info then local _,_,_,where=info(row.id);loc=where end
        if locations[loc] or loc=="INVTYPE_2HWEAPON" then keys[#keys+1]=k end
    end
    for k in pairs(db.manualItems and db.manualItems[guid] or {}) do keys[#keys+1]="manual:"..k end
    for k in pairs(db.inspectedItems and db.inspectedItems[guid] or {}) do keys[#keys+1]="inspected:"..k end
    table.sort(keys);return table.concat(keys,";")
end
function ns.EffectCoverage(payload,id,baselineId)
    local gaps,notes={},{}
    for _,itemId in ipairs({id,baselineId}) do
        for _,line in ipairs(payload.missingItemEffects and payload.missingItemEffects[itemId] or {}) do
            gaps[#gaps+1]=line
        end
    end
    for _,line in ipairs(payload.itemConditions and payload.itemConditions[id] or {}) do notes[#notes+1]=line end
    return #gaps>0 and table.concat(gaps,"; ") or nil, #notes>0 and table.concat(notes," ") or nil
end
function ns.ItemComparison(link)
    local usable,reason,status=ns.ItemEligibility(link)
    if usable==false then return nil,reason,status end
    if not ns.IsItemSimSupported(link) then return nil,"Item slot is not supported." end
    local id,suffix,enchant,unsupported=parts(link)
    if not id then return nil,"Item link is unavailable." end
    if not (ns.itemResults and ns.itemResults.catalogMode) then ns.QueueItem(link) end
    if unsupported then return nil,"This bonus-list or gem variant cannot be simulated by the exporter." end
    local fresh,why=ns.ItemComparisonsFresh()
    if not fresh then return nil,why end
    local p=ns.itemResults;local k=key(id,suffix,enchant)
    if p.errors and p.errors[k] then return nil,p.errors[k] end
    local row=p.items[k]
    if not row then
        if p.scope=="quick" then return nil,"Not in current quick comparisons. Hovering collects this item; Update sims in /guildsim saves it for the next quick comparison.","missing" end
        if p.catalogMode then
            if not p.complete then return nil,string.format("Catalog sim running: %d/%d variants ready. Load results after the helper advances.",p.completedVariants or 0,p.catalogVariants or 0) end
            return nil,"This exact variant is outside the supported pre-simulated catalog."
        end
        local requests=GuildSimBetaDB and GuildSimBetaDB.progressRequests
        local request=requests and requests[UnitGUID("player")]
        if not dirty and request then return nil,"Capture saved. When the desktop helper is ready, click Load results in /guildsim." end
        return nil,"Item collected in-game; not saved to the helper yet. Click Update sims in /guildsim."
    end
    local displayed=tostring(link):match("|h%[([^%]]+)%]|h")
    if suffix==0 and displayed and displayed~=row.name then return nil,"Displayed item variant differs from the simulated item." end
    local missing,conditions=ns.EffectCoverage(p,id,row.replacedId)
    return {delta=row.delta,percent=row.percent,dps=row.dps,baselineDps=p.baselineDps,
        baselineName=row.replacedName,baselineId=row.replacedId,inventorySlot=row.inventorySlot,
        provisional=row.provisional or missing~=nil,procProvisional=row.procProvisional,missingEffects=missing,conditions=conditions,exportedLevel=60,meanError95=row.meanError95,
        uncertain=row.uncertain,iterations=row.iterations,pairedError95=row.pairedError95,backend=row.backend,comparisonLabel=p.comparisonLabel}
end
GuildSimBetaItems={Compare=ns.ItemComparison,Supported=ns.IsItemSimSupported,Eligibility=ns.ItemEligibility}
function ns.SavedItemComparison(link)
    local p=ns.itemSnapshot
    if not p or p.guid~=UnitGUID("player") then return end
    local id,suffix,enchant=parts(link)
    if not id then return end
    local row=p.items[key(id,suffix,enchant)]
    if row then return row,p.generated end
end
function GuildSimBetaItems.Catalog()
    local fresh,why=ns.ItemComparisonsFresh()
    if fresh then return ns.itemResults end
    return nil,why
end
local queueWeapons=ns.QueueWeapons
ns.QueueWeapons=function(input)
    ns.QueueItems()
    local result=queueWeapons(input)
    if result then
        dirty=nil;noticeShown=nil
        if notice then notice:Hide() end
    end
    return result
end
function ns.FullComparison(link)
    if ns.IsItemSimSupported(link) then return ns.ItemComparison(link) end
    return ns.WeaponComparison and ns.WeaponComparison(link)
end
GuildSimBetaItems.FullCompare=ns.FullComparison

local function showNotice()
    if not dirty then if notice then notice:Hide() end;return end
    if InCombatLockdown and InCombatLockdown() then return end
    if noticeShown then return end
    if not notice then
        notice=CreateFrame("Button","GuildSimBetaUpdateNotice",UIParent,"UIPanelButtonTemplate")
        notice:SetSize(310,25);notice:SetPoint("TOP",UIParent,"TOP",0,-115)
        notice:SetText("Ret Sim: new items — Update sims")
        notice:SetScript("OnClick",function()ns.ReloadSimResults(true)end)
        local close=CreateFrame("Button",nil,notice,"UIPanelCloseButton")
        close:SetSize(24,24);close:SetPoint("RIGHT",notice,"RIGHT",0,0)
        close:SetScript("OnClick",function()notice:Hide()end)
    end
    noticeShown=true;notice:Show()
    if C_Timer then C_Timer.After(15,function()if notice then notice:Hide() end end) end
end
local function collect()
    scheduled=nil
    if InCombatLockdown and InCombatLockdown() then return end
    ns.QueueItems()
    if ns.InvalidateSimFreshness then ns.InvalidateSimFreshness() end
    if ns.itemResults and ns.LiveSimExport and not (ns.SameCatalogExport or ns.SameCombatExport)(ns.LiveSimExport(),ns.itemResults.sourceExport,ns.itemResults) then dirty=true end
    showNotice()
end
local events=CreateFrame("Frame")
for _,event in ipairs({"PLAYER_LOGIN","BAG_UPDATE_DELAYED","PLAYER_EQUIPMENT_CHANGED","PLAYER_TALENT_UPDATE","PLAYER_LEVEL_UP","PLAYER_REGEN_ENABLED","PLAYER_REGEN_DISABLED"}) do
    events:RegisterEvent(event)
end
events:SetScript("OnEvent",function(_,event)
    if event=="PLAYER_REGEN_DISABLED" then if notice then notice:Hide() end;return end
    if scheduled or not C_Timer then return end
    scheduled=true;C_Timer.After(8,collect)
end)
local function tooltip(tip)
    if not tip or not tip.GetItem then return end
    local _,link=tip:GetItem()
    if link and tip~=ShoppingTooltip1 and tip~=ShoppingTooltip2 then ns.lastInspectedItem=link end
    if link then
        local usable,why=ns.ItemEligibility(link)
        if usable==false then tip:AddLine("Ret Sim: "..why,1,0.4,0.3,true);return end
    end
    if link and not ns.IsItemSimSupported(link) then
        if ns.QueueInspectedItem(link) and C_Timer then C_Timer.After(0,showNotice) end
        return
    end
    if link and ns.IsItemSimSupported(link) then
        local added=ns.QueueInspectedItem(link)
        if added and C_Timer then C_Timer.After(0,showNotice) end
        if ns.payload and ns.payload.guid==UnitGUID("player") then
            local full,why=ns.ItemComparison(link)
            tip:AddLine("Ret Sim — full item comparison",0.3,0.85,1)
            if full then
                if full.comparisonLabel then tip:AddLine(full.comparisonLabel.."; catalog DPS, not current trinket DPS.",0.7,0.85,1,true) end
                tip:AddLine(string.format("%+.2f DPS (%+.2f%%) replacing %s",full.delta,full.percent,full.baselineName),full.delta>=0 and 0.3 or 1,full.delta>=0 and 1 or 0.4,0.5,true)
                if full.iterations then tip:AddLine(string.format("%d iterations; estimated mean DPS error ±%.2f",full.iterations,full.meanError95 or 0),0.7,0.7,0.7,true) end
                if full.pairedError95 then tip:AddLine(string.format("WoWSims bulk: swap DPS error ±%.2f (95%%)",full.pairedError95),0.7,0.85,1,true) end
                if full.uncertain then tip:AddLine("Difference is within estimated simulation sampling error.",1,0.75,0.3,true) end
                if full.procProvisional then tip:AddLine("Proc-rate assumption is provisional.",1,0.75,0.3,true) end
                if full.missingEffects then tip:AddLine("Partial model; no upgrade arrow. WoWSims missing: "..full.missingEffects,1,0.75,0.3,true) end
                if full.conditions then tip:AddLine(full.conditions,0.8,0.8,0.8,true) end
            else
                tip:AddLine(why,1,0.75,0.3,true)
                local saved,generated=ns.SavedItemComparison(link)
                if saved then
                    tip:AddLine(string.format("Previous catalog setup: %+.2f DPS (%+.2f%%)",saved.delta,saved.percent),0.65,0.65,0.65,true)
                    if date then tip:AddLine("Saved "..date("%m/%d %H:%M",generated).."; historical comparison, no upgrade arrow.",0.65,0.65,0.65,true) end
                end
            end
        end
    end
end
if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item,function(t)pcall(tooltip,t)end)
    GuildSimBetaItems.OwnsTooltip=true
elseif GameTooltip and GameTooltip.HookScript then
    GameTooltip:HookScript("OnTooltipSetItem",function(t)pcall(tooltip,t)end)
    GuildSimBetaItems.OwnsTooltip=true
end

function ns.ShowItemResults()
    local p=ns.itemResults
    local lines={"Full armor and jewelry simulations", ""}
    local fresh,why=ns.ItemComparisonsFresh()
    if not fresh then lines[#lines+1]=why end
    if p then
        local engine=ns.payload and ns.payload.wowsims
        if engine then lines[#lines+1]="WoWSims "..(engine.release_tag or "").." — "..string.sub(engine.upstream_commit or "",1,12) end
        if p.comparisonLabel then lines[#lines+1]=p.comparisonLabel..". Catalog DPS uses this pair rather than your currently worn trinkets." end
        lines[#lines+1]=string.format("Baseline %.2f DPS; %d iterations per set; %ds; boss level %d",p.baselineDps,p.iterations,p.duration,p.targetLevel)
        lines[#lines+1]="Each comparison changes one item, using that item's captured enchant. Rings/trinkets test both legal slots."
        lines[#lines+1]="Close results may be statistical ties. Combined swaps need a new capture."
        local rows={}
        if p.compact then for key in pairs(p.compact) do rows[#rows+1]=p.items[key] end
        else for _,row in pairs(p.items) do rows[#rows+1]=row end end
        table.sort(rows,function(a,b)return a.delta>b.delta end)
        for index,row in ipairs(rows) do
            if index>100 then break end
            lines[#lines+1]=string.format("%s: %+.2f DPS (%+.2f%%), replace %s%s",row.name,row.delta,row.percent,row.replacedName,row.provisional and " [partial model / provisional]" or "")
        end
        if #rows>100 then lines[#lines+1]="Showing the top 100. All completed items are available in tooltips." end
    end
    if not ns.itemWindow then
        local f=CreateFrame("Frame","GuildSimBetaItemResultsFrame",UIParent,"BackdropTemplate");ns.itemWindow=f
        f:SetSize(950,650);f:SetPoint("CENTER");f:SetFrameStrata("DIALOG")
        f:SetBackdrop({bgFile="Interface\\DialogFrame\\UI-DialogBox-Background",edgeFile="Interface\\DialogFrame\\UI-DialogBox-Border",tile=true,tileSize=32,edgeSize=24,insets={left=6,right=6,top=6,bottom=6}})
        f:EnableMouse(true);f:SetMovable(true);f:RegisterForDrag("LeftButton");f:SetScript("OnDragStart",f.StartMoving);f:SetScript("OnDragStop",f.StopMovingOrSizing)
        local close=CreateFrame("Button",nil,f,"UIPanelCloseButton");close:SetPoint("TOPRIGHT",-5,-5)
        local scroll=CreateFrame("ScrollFrame",nil,f,"UIPanelScrollFrameTemplate");scroll:SetPoint("TOPLEFT",24,-35);scroll:SetPoint("BOTTOMRIGHT",-46,28)
        f.content=CreateFrame("Frame",nil,scroll);f.content:SetSize(870,1800);scroll:SetScrollChild(f.content)
        f.text=f.content:CreateFontString(nil,"OVERLAY","GameFontHighlight");f.text:SetPoint("TOPLEFT");f.text:SetWidth(865);f.text:SetJustifyH("LEFT")
        if UISpecialFrames then table.insert(UISpecialFrames,"GuildSimBetaItemResultsFrame") end
    end
    ns.itemWindow.text:SetText(table.concat(lines,"\n"));ns.itemWindow.content:SetHeight(math.max(100,ns.itemWindow.text:GetStringHeight()+30));ns.itemWindow:Show()
end

-- Dedicated native-simulation browser and paper-doll companion.
local browser, poolEdited, matchupEdited
local browserSlots={{"Head",1,1},{"Neck",2,2},{"Shoulders",3,3},{"Back",15,4},
    {"Chest",5,5},{"Wrists",9,6},{"Hands",10,7},{"Waist",6,8},{"Legs",7,9},
    {"Feet",8,10},{"Ring 1",11,11},{"Ring 2",12,11},{"Trinket 1",13,12},{"Trinket 2",14,12},{"Two-hand",16,13},{"Relic",18,14}}
local sourceGroups={"All sources","Drop","Quest","Crafted","Vendor","Other"}
local function trinketDB()
    GuildSimBetaDB=GuildSimBetaDB or {}
    local db=GuildSimBetaDB;local guid=UnitGUID("player")
    db.trinketPool=db.trinketPool or {};db.trinketPool[guid]=db.trinketPool[guid] or {}
    db.trinketExclusions=db.trinketExclusions or {};db.trinketExclusions[guid]=db.trinketExclusions[guid] or {}
    return db.trinketPool[guid],db.trinketExclusions[guid]
end
function ns.RememberTrinket(link)
    local id,suffix,enchant,unsupported=parts(link)
    if not id or unsupported then return end
    local info=(C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    local loc;if info then local _,_,_,location=info(link);loc=location end
    if loc~="INVTYPE_TRINKET" then return end
    for _,utility in ipairs((ns.payload and ns.payload.mountTrinketIds) or {11122,12846}) do if utility~=19812 and id==utility then return end end
    local pool=trinketDB();pool[key(id,suffix,enchant)]={id=id,randomSuffix=suffix,enchant=enchant}
end
function ns.EditTrinketPool(input,exclude)
    local id,suffix,enchant,unsupported=parts(input)
    if not id or unsupported then print("Ret Sim: enter a trinket item ID or unmodified item link.");return false end
    local info=(C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    local loc;if info then local _,_,_,location=info(tonumber(input) or input);loc=location end
    if loc and loc~="INVTYPE_TRINKET" then print("Ret Sim: this item is not a trinket.");return false end
    for _,utility in ipairs((ns.payload and ns.payload.mountTrinketIds) or {11122,12846}) do
        if utility~=19812 and id==utility then print("Ret Sim: riding and utility trinkets are excluded from the combat pool.");return false end
    end
    local pool,excluded=trinketDB()
    excluded[id]=exclude or nil
    if not exclude then pool[key(id,suffix,enchant)]={id=id,randomSuffix=suffix,enchant=enchant} end
    poolEdited=true
    print(exclude and "Ret Sim: trinket excluded. Update sims to save the pool." or "Ret Sim: trinket added to the pool. Update sims to save it.")
    return true
end
local function itemLink(spec)
    return string.format("item:%d:%d:0:0:0:0:%d:0",spec.id,spec.enchant or 0,spec.randomSuffix or 0)
end
local function pairData()
    local profile=ns.trinketPairTarget or "default"
    if ns.trinketPairProfiles then return ns.trinketPairProfiles[profile] end
    if profile=="default" then return ns.trinketPairs end
end
local function profileLabel()
    local key=ns.trinketPairTarget or "default"
    for _,profile in ipairs(ns.fightProfiles or {}) do if profile.key==key then return profile.label end end
    return key=="default" and "Raid setup" or key
end
function ns.RequestFightProfile(key)
    local known=false
    for _,profile in ipairs(ns.fightProfiles or {}) do if profile.key==key then known=true end end
    if not known then print("Ret Sim: this matchup is not supported by the installed engine.");return false end
    GuildSimBetaDB=GuildSimBetaDB or {};local db=GuildSimBetaDB;local guid=UnitGUID("player")
    db.fightProfileRequests=db.fightProfileRequests or {};db.fightProfileRequests[guid]=db.fightProfileRequests[guid] or {}
    db.fightProfileRequests[guid][key]=true;matchupEdited=true
    return true
end
local function browserRows(slotType,pairMode)
    local rows={};local p=ns.itemResults
    if pairMode then
        local pairs=pairData()
        if not pairs then return rows,"This matchup is not simulated. Choose Sim this matchup to request it." end
        local expectedEngine=ns.payload and ns.payload.wowsims and ns.payload.wowsims.upstream_commit or (p and p.engineCommit)
        local expectedModel=p and p.combatModel
        local fresh=pairs and pairs.guid==UnitGUID("player") and ns.LiveSimExport and
            ns.SameCatalogExport(ns.LiveSimExport(),pairs.sourceExport,pairs) and time()-pairs.generated<7*86400 and
            (not expectedEngine or pairs.engineCommit==expectedEngine) and (not expectedModel or pairs.baseCombatModel==expectedModel)
        for _,row in ipairs(pairs and pairs.rows or {}) do
            rows[#rows+1]={id=row.first.id,name=row.firstName.." + "..row.secondName,
                first=row.first,second=row.second,source=(row.provisional and "Partial model" or row.uncertain and "Within sampling error" or "Both slot orders tested"),
                dps=fresh and row.dps or nil,delta=fresh and row.delta or nil,
                provisional=row.provisional,uncertain=row.uncertain,detail=row,quality=3}
        end
        if fresh then return rows end
        return rows,"Trinket pair results need a saved capture and simulation."
    end
    local fresh,why=ns.ItemComparisonsFresh()
    local known={}
    if slotType==13 then
        local context,result=ns.WeaponData("equipped")
        fresh=context~=nil;if fresh then why=nil else why=result end
        for _,row in ipairs(context and context.weapons or {}) do
            known[row.id..":"..(row.randomSuffix or 0)]=true
            local meta=p and p.browserItems and p.browserItems[row.id] or {}
            rows[#rows+1]={id=row.id,name=row.name,source=meta[5] or "Acquisition source unverified",group=meta[4] or "Other",quality=meta[2] or 3,icon=meta[3],
                first={id=row.id,randomSuffix=row.randomSuffix,enchant=context.enchant},
                dps=row.dps,delta=row.delta,provisional=row.provisional or row.provisionalProc,uncertain=row.uncertain}
        end
    elseif p then
        local function add(k)
            local row=p.items[k];if not row then return end
            local meta=p.browserItems and p.browserItems[row.id]
            if not meta or meta[1]~=slotType then return end
            known[row.id..":"..(row.randomSuffix or 0)]=true
            local name=row.name or p.names[row.id];local suffix=p.browserSuffixNames and p.browserSuffixNames[row.randomSuffix or 0]
            if suffix and suffix~="" and not name:find(suffix,1,true) then name=name.." "..suffix end
            rows[#rows+1]={id=row.id,name=name,source=meta[5],group=meta[4],quality=meta[2],icon=meta[3],
                first={id=row.id,randomSuffix=row.randomSuffix,enchant=row.enchant},
                dps=fresh and row.dps or nil,delta=fresh and row.delta or nil,
                provisional=row.provisional,uncertain=row.uncertain,screening=(row.iterations or 0)<10000}
        end
        for k in pairs(p.compact or p.items or {}) do add(k) end
    end
    for id,meta in pairs(p and p.browserItems or {}) do
        if meta[1]==slotType then
            for _,suffix in ipairs(meta[8] or {0}) do
                if not known[id..":"..suffix] then
                    local name=p.names[id] or p.names[tostring(id)] or tostring(id)
                    local suffixName=p.browserSuffixNames and p.browserSuffixNames[suffix]
                    if suffixName and suffixName~="" then name=name.." "..suffixName end
                    rows[#rows+1]={id=id,name=name,source=meta[5],group=meta[4],quality=meta[2],icon=meta[3],first={id=id,randomSuffix=suffix}}
                end
            end
        end
    end
    return rows,fresh and nil or why
end
ns.GearBrowserRows=browserRows
local function text(parent,label,x,y,width,font)
    local fs=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlight")
    local face=fs:GetFont()
    if type(face)=="string" then fs:SetFont(face,font=="GameFontNormalLarge" and 19 or font=="GameFontNormalSmall" and 11 or 13,"") end
    fs:SetPoint("TOPLEFT",x,y);fs:SetWidth(width);fs:SetJustifyH("LEFT");fs:SetWordWrap(false);fs:SetText(label or "")
    return fs
end
local function surface(frame)
    frame:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=false,edgeSize=10,insets={left=2,right=2,top=2,bottom=2}})
    frame:SetBackdropColor(.025,.03,.038,1);frame:SetBackdropBorderColor(.59,.44,.18,1)
end
local qualityPalette={
    [0]={.65,.69,.76},[1]={.96,.97,1},[2]={.25,1,.47},[3]={.28,.68,1},
    [4]={.79,.40,1},[5]={1,.62,.16},[6]={1,.84,.43},[7]={.46,.88,1},
}
local function button(parent,label,x,y,width,fn)
    local b=CreateFrame("Button",nil,parent,"BackdropTemplate")
    b:SetPoint("TOPLEFT",x,y);b:SetSize(width,28);surface(b)
    b.caption=text(b,label,0,0,width-8);b.caption:ClearAllPoints();b.caption:SetPoint("CENTER");b.caption:SetJustifyH("CENTER")
    b.SetText=function(self,value)self.caption:SetText(value)end
    b.SetSelected=function(self,on)
        self.selected=on
        self:SetBackdropColor(on and .29 or .075,on and .20 or .085,on and .065 or .10,1)
        self:SetBackdropBorderColor(on and 1 or .36,on and .75 or .39,on and .25 or .45,1)
        self.caption:SetTextColor(on and 1 or .93,on and .85 or .95,on and .35 or 1)
    end
    b:SetSelected(false)
    b:SetScript("OnEnter",function(self)self:SetBackdropBorderColor(1,.82,.35,1)end)
    b:SetScript("OnLeave",function(self)self:SetSelected(self.selected)end)
    b:SetScript("OnClick",fn);return b
end
local function tooltipItem(frame,link)
    if not GameTooltip then return end
    GameTooltip:SetOwner(frame,"ANCHOR_RIGHT");GameTooltip:SetHyperlink(link)
end
local function refreshBrowser()
    if not browser then return end
    local f=browser;local p=ns.itemResults;local pairMode=f.mode=="pairs"
    local data=p;if pairMode then data=pairData() end
    f.title:SetText(pairMode and "Trinket combinations" or browserSlots[f.slot][1].." upgrades")
    local equipped=GetInventoryItemLink and GetInventoryItemLink("player",browserSlots[f.slot][2])
    local equippedName=equipped and equipped:match("|h%[([^%]]+)%]|h")
    f.subtitle:SetText(pairMode and (profileLabel().." target · two trinkets change together; all other gear stays fixed.") or equippedName and "Equipped: "..equippedName or "Compare one upgrade at a time against your reference setup.")
    local reference=(data and data.comparisonLabel or "No simulation setup loaded"):gsub("^Reference trinkets: ","")
    f.setup:SetText((data and data.baselineDps and string.format("Reference: %.1f DPS   ·   ",data.baselineDps) or "")..reference)
    local rows,why=browserRows(browserSlots[f.slot][3],pairMode)
    local query=f.search:GetText():lower();local selected=sourceGroups[f.source]
    local filtered={}
    for _,row in ipairs(rows) do
        if (query=="" or (row.name or ""):lower():find(query,1,true) or tostring(row.id)==query or (row.source or ""):lower():find(query,1,true)) and
            (pairMode or selected=="All sources" or row.group==selected) and
            (pairMode or not f.upgrades:GetChecked() or (row.delta and row.delta>0)) then filtered[#filtered+1]=row end
    end
    table.sort(filtered,function(a,b)
        if (a.dps~=nil)~=(b.dps~=nil) then return a.dps~=nil end
        if a.dps and a.dps~=b.dps then return a.dps>b.dps end
        return (a.name or "")<(b.name or "")
    end)
    local pageSize=pairMode and 11 or 14
    local pages=math.max(1,math.ceil(#filtered/pageSize));f.page=math.min(f.page,pages)
    local simulated=0;for _,row in ipairs(filtered) do if row.dps then simulated=simulated+1 end end
    f.pageText:SetText(string.format("%d simulated / %d listed   ·   Page %d of %d",simulated,#filtered,f.page,pages))
    f.status:SetText(poolEdited and "Pool edited. Click Update sims to save it; load results when the helper is ready." or why or
        "Reference DPS. ~ screening estimate   * partial model   ≈ within sampling error. Hover for item details.")
    if pairMode and data and not poolEdited then
        local count=0;for _ in pairs(data.pool or {}) do count=count+1 end
        local message=string.format("%d pool trinkets • %d pairs • %d slot orders. Close DPS results may be ties; * means partial model.",count,#(data.rows or {}),data.testedOrders or 0)
        for id,reason in pairs(data.poolErrors or {}) do message=message.." Excluded "..id..": "..reason;break end
        f.status:SetText(why or message)
    end
    f.sourceButton:SetShown(not pairMode);f.upgrades:SetShown(not pairMode);f.upgradesLabel:SetShown(not pairMode)
    f.poolButton:SetShown(pairMode)
    f.targetButton:SetShown(pairMode)
    f.targetButton:SetText("Target: "..profileLabel())
    f.matchupButton:SetShown(pairMode and why~=nil)
    if matchupEdited then f.status:SetText("Matchup queued. Update sims saves the request; load results when the helper is ready.") end
    if not pairMode then f.targetMenu:Hide() end
    if not pairMode then f.poolEditor:Hide() end
    if pairMode then f.sourceMenu:Hide() end
    f.empty:SetShown(#filtered==0);f.clearFilters:SetShown(#filtered==0)
    f.gearTab:SetSelected(not pairMode);f.pairTab:SetSelected(pairMode)
    for i,b in ipairs(f.slots) do
        local slot=browserSlots[i];local link=GetInventoryItemLink and GetInventoryItemLink("player",slot[2])
        local name=link and link:match("|h%[([^%]]+)%]|h")
        b.label:SetText((f.slot==i and "|cffffd100" or "|cffbbbbbb")..slot[1].."|r\n"..(name or "Empty"))
        b.link=link
        b.icon:SetTexture((GetInventoryItemTexture and GetInventoryItemTexture("player",slot[2])) or "Interface\\Icons\\INV_Misc_QuestionMark")
    end
    for i,b in ipairs(f.rows) do
        local row=i<=pageSize and filtered[(f.page-1)*pageSize+i]
        b:ClearAllPoints();b:SetPoint("TOPLEFT",268,-228-(i-1)*(pairMode and 40 or 32));b:SetHeight(pairMode and 39 or 31)
        if row then
            b.data=row;b:Show()
            local iconAPI=(C_Item and C_Item.GetItemIconByID) or GetItemIcon
            b.icon:SetTexture((iconAPI and iconAPI(row.id)) or (row.icon and row.icon~="" and ("Interface\\Icons\\"..row.icon)) or "Interface\\Icons\\INV_Misc_QuestionMark")
            if pairMode then
                local icon=GetItemIcon and GetItemIcon(row.second.id);b.icon2:SetTexture(icon or "Interface\\Icons\\INV_Misc_QuestionMark");b.icon2:Show()
            else b.icon2:Hide() end
            local color=qualityPalette[row.quality or 1] or qualityPalette[1]
            b.item:SetText(pairMode and (row.detail.firstName.."\n"..row.detail.secondName) or row.name)
            b.item:SetHeight(pairMode and 34 or 18)
            b.item:SetTextColor(color[1],color[2],color[3])
            b.model:SetText(not row.dps and "Not simulated" or row.provisional and "Partial model" or row.uncertain and "Statistical tie" or row.screening and "Screening estimate" or "Simulated")
            b.model:SetShown(not pairMode)
            b.source:SetText(row.source or "Acquisition source unverified")
            b.dps:SetText(row.dps and string.format("%.1f",row.dps) or "—")
            b.delta:SetText(row.delta and string.format("%+.1f",row.delta) or "—")
            if row.provisional then b.delta:SetTextColor(1,.77,.28)
            elseif row.uncertain then b.delta:SetTextColor(.70,.76,.86)
            elseif row.delta and row.delta>0 then b.delta:SetTextColor(.25,1,.55)
            elseif row.delta and row.delta<0 then b.delta:SetTextColor(1,.42,.36)
            else b.delta:SetTextColor(.65,.69,.75) end
        else b:Hide() end
    end
end
function ns.ShowGearBrowser(mode,slot,docked)
    if not browser then
        local f=CreateFrame("Frame","GuildSimBetaGearBrowser",UIParent,"BackdropTemplate");browser=f
        f:SetSize(1180,750);f:SetPoint("CENTER");f:SetFrameStrata("DIALOG");f:SetClampedToScreen(true)
        local body=CreateFrame("Frame",nil,f);f.body=body;body:SetSize(1180,750);body:SetPoint("TOPLEFT")
        surface(f)
        f:EnableMouse(true);f:SetMovable(true);f:RegisterForDrag("LeftButton");f:SetScript("OnDragStart",f.StartMoving);f:SetScript("OnDragStop",f.StopMovingOrSizing)
        local close=CreateFrame("Button",nil,f,"UIPanelCloseButton");close:SetPoint("TOPRIGHT",-5,-5)
        f.title=text(f,"Gear upgrades",22,-22,550,"GameFontNormalLarge")
        f.subtitle=text(f,"",22,-49,1110);f.setup=text(f,"",22,-70,1110)
        f.slot=1;f.page=1;f.source=1;f.mode="gear"
        f.gearTab=button(f,"Gear",22,-97,150,function()f.mode="gear";f.page=1;f.search:SetText("");refreshBrowser()end)
        f.pairTab=button(f,"Trinket pairs",179,-97,150,function()f.mode="pairs";f.page=1;f.search:SetText("");refreshBrowser()end)
        local sync=button(body,"Update sims",839,-22,150,function()ns.ReloadSimResults(true)end);sync:SetSelected(true)
        button(body,"Load results",996,-22,150,function()ns.ReloadSimResults(false)end)
        f.leftTitle=text(f,"Equipped gear — select a slot",22,-140,230,"GameFontNormal")
        f.slots={}
        for i,slot in ipairs(browserSlots) do
            local index=i;local b=CreateFrame("Button",nil,f)
            b:SetPoint("TOPLEFT",22,-165-(i-1)*34);b:SetSize(230,33)
            b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetPoint("LEFT");b.icon:SetSize(29,29)
            b.label=text(b,"",35,-2,193);b.label:SetHeight(30)
            b:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight")
            b:SetScript("OnClick",function()f.slot=index;f.mode="gear";f.page=1;refreshBrowser()end)
            b:SetScript("OnEnter",function()if b.link then tooltipItem(b,b.link) end end)
            b:SetScript("OnLeave",function()if GameTooltip then GameTooltip:Hide()end end)
            f.slots[i]=b
        end
        f.search=CreateFrame("EditBox",nil,body,"InputBoxTemplate");f.search:SetPoint("TOPLEFT",273,-139);f.search:SetSize(220,25);f.search:SetAutoFocus(false)
        f.search:SetScript("OnTextChanged",function()f.page=1;refreshBrowser()end)
        f.search:SetScript("OnEscapePressed",function(self)self:ClearFocus()end)
        f.sourceMenu=CreateFrame("Frame",nil,f,"BackdropTemplate");f.sourceMenu:SetSize(174,212);f.sourceMenu:SetPoint("TOPLEFT",body,"TOPLEFT",503,-172);surface(f.sourceMenu);f.sourceMenu:SetFrameStrata("FULLSCREEN_DIALOG");f.sourceMenu:Hide()
        for i,label in ipairs(sourceGroups) do
            local index=i
            button(f.sourceMenu,label,8,-8-(i-1)*33,158,function()f.source=index;f.sourceButton:SetText(label);f.sourceMenu:Hide();f.page=1;refreshBrowser()end)
        end
        f.sourceButton=button(body,"All sources",503,-139,125,function()f.sourceMenu:SetShown(not f.sourceMenu:IsShown())end)
        local profiles=ns.fightProfiles or {{key="default",label="Raid setup"}}
        f.targetMenu=CreateFrame("Frame",nil,f,"BackdropTemplate");f.targetMenu:SetSize(430,math.ceil(#profiles/2)*31+16);f.targetMenu:SetPoint("TOPLEFT",body,"TOPLEFT",503,-172);surface(f.targetMenu);f.targetMenu:SetFrameStrata("FULLSCREEN_DIALOG");f.targetMenu:Hide()
        for i,profile in ipairs(profiles) do
            local key=profile.key
            button(f.targetMenu,profile.label,8+((i-1)%2)*210,-8-math.floor((i-1)/2)*31,202,function()
                ns.trinketPairTarget=key;f.page=1;f.targetMenu:Hide();refreshBrowser()
            end)
        end
        f.targetButton=button(body,"Target: Raid setup",503,-139,195,function()f.targetMenu:SetShown(not f.targetMenu:IsShown())end)
        f.matchupButton=button(body,"Sim this matchup",710,-139,170,function()
            if ns.RequestFightProfile(ns.trinketPairTarget or "default") then ns.ReloadSimResults(true) end
        end)
        f.upgrades=CreateFrame("CheckButton",nil,body,"UICheckButtonTemplate");f.upgrades:SetPoint("TOPLEFT",640,-137);f.upgrades:SetSize(26,26)
        f.upgradesLabel=text(body,"Upgrades only",670,-144,120);f.upgrades:SetScript("OnClick",function()f.page=1;refreshBrowser()end)
        f.poolEditor=CreateFrame("Frame",nil,f,"BackdropTemplate");f.poolEditor:SetSize(390,156);f.poolEditor:SetPoint("TOPRIGHT",-20,-175);f.poolEditor:SetFrameStrata("FULLSCREEN_DIALOG");surface(f.poolEditor);f.poolEditor:Hide()
        text(f.poolEditor,"Edit trinket pool",16,-14,330,"GameFontNormal")
        local poolClose=CreateFrame("Button",nil,f.poolEditor,"UIPanelCloseButton");poolClose:SetPoint("TOPRIGHT",-2,-2)
        text(f.poolEditor,"Item ID or item link",16,-45,350)
        f.poolInput=CreateFrame("EditBox",nil,f.poolEditor,"InputBoxTemplate");f.poolInput:SetPoint("TOPLEFT",20,-68);f.poolInput:SetSize(350,25);f.poolInput:SetAutoFocus(false)
        f.poolInput:SetScript("OnEscapePressed",function()f.poolEditor:Hide()end)
        button(f.poolEditor,"Add trinket",16,-111,170,function()if ns.EditTrinketPool(f.poolInput:GetText(),false) then f.poolInput:SetText("");refreshBrowser()end end)
        button(f.poolEditor,"Exclude trinket",198,-111,170,function()if ns.EditTrinketPool(f.poolInput:GetText(),true) then f.poolInput:SetText("");refreshBrowser()end end)
        f.poolButton=button(body,"Manage pool",991,-139,155,function()f.poolEditor:SetShown(not f.poolEditor:IsShown())end)
        f.searchHint=text(body,"Search items or source…",282,-145,200);f.searchHint:SetTextColor(.64,.69,.77)
        f.search:SetScript("OnTextChanged",function()f.page=1;f.searchHint:SetShown(f.search:GetText()=="");refreshBrowser()end)
        text(body,"Item / trinket pair",333,-203,325,"GameFontNormal")
        text(body,"Source / model status",690,-203,220,"GameFontNormal")
        text(body,"Sim DPS",940,-203,80,"GameFontNormal");text(body,"DPS gain",1030,-203,120,"GameFontNormal")
        f.rows={}
        f.empty=text(body,"No items match these filters.",273,-340,870);f.empty:SetJustifyH("CENTER");f.empty:SetTextColor(.7,.74,.8)
        f.clearFilters=button(body,"Clear filters",620,-374,170,function()
            f.search:SetText("");f.source=1;f.sourceButton:SetText(sourceGroups[1]);f.upgrades:SetChecked(false);f.page=1;refreshBrowser()
        end)
        for i=1,14 do
            local b=CreateFrame("Button",nil,body);b:SetPoint("TOPLEFT",268,-228-(i-1)*24);b:SetSize(884,23)
            b:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight")
            b.background=b:CreateTexture(nil,"BACKGROUND");b.background:SetAllPoints();b.background:SetColorTexture(i%2==0 and .06 or .035,i%2==0 and .07 or .045,i%2==0 and .09 or .06,1)
            b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetPoint("LEFT",2,0);b.icon:SetSize(26,26)
            b.icon2=b:CreateTexture(nil,"ARTWORK");b.icon2:SetPoint("LEFT",25,0);b.icon2:SetSize(22,22)
            b.item=text(b,"",60,-2,345);b.source=text(b,"",422,-7,236);b.dps=text(b,"",674,-7,80);b.delta=text(b,"",764,-7,110)
            b.dps:SetJustifyH("RIGHT");b.delta:SetJustifyH("RIGHT")
            b.model=text(b,"",60,-18,345,"GameFontNormalSmall");b.model:SetTextColor(.62,.66,.72)
            b:SetScript("OnEnter",function()
                if not b.data then return end
                tooltipItem(b,itemLink(b.data.first))
                if GameTooltip and b.data.detail then
                    local row=b.data.detail
                    GameTooltip:AddLine("Pair: "..row.firstName.." + "..row.secondName,1,.82,.35,true)
                    GameTooltip:AddLine("Slot 13: "..row.firstName.."; slot 14: "..row.secondName,.8,.8,.8,true)
                    GameTooltip:AddLine(string.format("%d iterations; swap DPS error ±%.2f (95%%).",row.iterations,row.pairedError95),.7,.85,1,true)
                    for _,order in ipairs(row.orders or {}) do
                        local active=pairData();local pool=active and active.pool or {}
                        local a=pool[order.first];local b=pool[order.second]
                        GameTooltip:AddLine(string.format("Top %s / bottom %s: %.2f DPS",a and a.name or order.first,b and b.name or order.second,order.dps),.8,.8,.8,true)
                    end
                    for id,notes in pairs(row.missingEffects or {}) do for _,note in ipairs(notes) do GameTooltip:AddLine("Missing effect "..id..": "..note,1,.65,.25,true) end end
                    GameTooltip:AddLine("On-use timing follows WoWSims; this is not an exhaustive use-timing search.",.8,.8,.8,true)
                    GameTooltip:Show()
                end
            end)
            b:SetScript("OnLeave",function()if GameTooltip then GameTooltip:Hide()end end)
            b:SetScript("OnClick",function()if b.data and HandleModifiedItemClick then HandleModifiedItemClick(itemLink(b.data.first))end end)
            f.rows[i]=b
        end
        button(body,"Previous",273,-684,105,function()f.page=math.max(1,f.page-1);refreshBrowser()end)
        button(body,"Next",385,-684,105,function()f.page=f.page+1;refreshBrowser()end)
        f.pageText=text(body,"",505,-692,600)
        f.status=text(body,"",273,-721,872,"GameFontNormalSmall");f.status:SetHeight(16)
        f:EnableMouseWheel(true);f:SetScript("OnMouseWheel",function(_,delta)f.page=math.max(1,f.page+(delta<0 and 1 or -1));refreshBrowser()end)
        if UISpecialFrames then table.insert(UISpecialFrames,"GuildSimBetaGearBrowser") end
    end
    if mode then
        if mode~=browser.mode then browser.search:SetText("") end
        browser.mode=mode;browser.page=1
    end
    if slot then
        if slot~=browser.slot then browser.search:SetText("") end
        browser.slot=slot;browser.page=1
    end
    local panel=ns.characterPanel
    if docked==nil then docked=panel and panel:IsShown() or false end
    browser.docked=docked and panel~=nil
    browser:ClearAllPoints();browser.body:ClearAllPoints()
    if browser.docked then
        browser:SetWidth(934);browser.body:SetPoint("TOPLEFT",browser,"TOPLEFT",-246,0)
        browser:SetPoint("TOPLEFT",panel,"TOPRIGHT",4,0)
        local rootHeight=UIParent.GetHeight and UIParent:GetHeight() or 0
        local rootWidth=UIParent.GetWidth and UIParent:GetWidth() or 0
        local right=panel.GetRight and panel:GetRight() or 0
        local scale=panel.GetEffectiveScale and panel:GetEffectiveScale() or 1
        local rootScale=UIParent.GetEffectiveScale and UIParent:GetEffectiveScale() or 1
        right=(right or 0)*scale/rootScale
        local fit=math.min(1,rootHeight>0 and (rootHeight-30)/750 or 1,rootWidth>right+20 and (rootWidth-right-10)/934 or 1)
        if fit>=.85 then browser:SetScale(fit) else browser.docked=false end
    end
    if not browser.docked then
        browser:ClearAllPoints();browser:SetWidth(1180);browser:SetScale(1);browser.body:SetPoint("TOPLEFT");browser:SetPoint("CENTER")
    end
    browser.subtitle:SetWidth(browser.docked and 884 or 1110);browser.setup:SetWidth(browser.docked and 884 or 1110)
    refreshBrowser()
    browser.leftTitle:SetShown(not browser.docked)
    for _,b in ipairs(browser.slots) do b:SetShown(not browser.docked) end
    browser:Show()
    if ns.UpdateCharacterPanel then ns.UpdateCharacterPanel() end
end
ns.ShowItemResults=function()ns.ShowGearBrowser("gear")end
ns.ShowTrinketPairs=function()ns.ShowGearBrowser("pairs")end

-- A native companion to the paper doll. No dependency on Leveling BiS.
local characterHooked,dockPending
local function characterHost()
    local custom=rawget(_G,"DaylightUICharacter")
    if custom and custom.IsShown and custom:IsShown() then return custom end
    return CharacterFrame
end
local function updateCharacterPanel()
    dockPending=nil
    local panel=ns.characterPanel;if not panel then return end
    local host=characterHost();if not host then return end
    panel:ClearAllPoints()
    panel:SetPoint("TOPLEFT",host,"TOPRIGHT",4,0);panel:SetPoint("BOTTOMLEFT",host,"BOTTOMRIGHT",4,0)
    local width=UIParent.GetWidth and UIParent:GetWidth() or 0
    local right=host.GetRight and host:GetRight() or 0
    local onLeft=width>0 and right and right+324>width
    if onLeft then
        panel:ClearAllPoints();panel:SetPoint("TOPRIGHT",host,"TOPLEFT",-4,0);panel:SetPoint("BOTTOMRIGHT",host,"BOTTOMLEFT",-4,0)
    end
    local p=ns.itemResults;local fresh=ns.ItemComparisonsFresh()
    panel.baseline:SetText(fresh and p and p.baselineDps and string.format("%.1f DPS",p.baselineDps) or "Needs sync")
    local current=0;for _ in pairs(p and (p.compact or p.items) or {}) do current=current+1 end
    panel.reference:SetText(string.format("Reference setup  ·  %d / %d simulated",current,p and p.catalogVariants or current))
    panel.coverage:SetText("Select a slot to compare upgrades")
    local height=panel.GetHeight and panel:GetHeight() or 600
    if (height or 600)<480 then
        panel:ClearAllPoints();panel:SetHeight(480)
        if onLeft then panel:SetPoint("TOPRIGHT",host,"TOPLEFT",-4,0) else panel:SetPoint("TOPLEFT",host,"TOPRIGHT",4,0) end
        height=480
    end
    local rowHeight=math.max(16,math.min(27,((height or 600)-162)/#browserSlots))
    for i,b in ipairs(panel.rows) do
        local slot=browserSlots[i]
        b:ClearAllPoints();b:SetPoint("TOPLEFT",12,-108-(i-1)*rowHeight);b:SetSize(296,rowHeight)
        b.icon:SetSize(rowHeight-2,rowHeight-2)
        local link=GetInventoryItemLink and GetInventoryItemLink("player",slot[2])
        b.link=link;b.item:SetText(link and link:match("|h%[([^%]]+)%]|h") or "Empty")
        local id=link and tonumber(link:match("item:(%d+)"))
        local meta=id and p and p.browserItems and p.browserItems[id]
        local color=meta and qualityPalette[meta[2]] or qualityPalette[1]
        b.item:SetTextColor(color[1],color[2],color[3])
        b.selected:SetShown(browser and browser:IsShown() and browser.mode=="gear" and browser.slot==i or false)
        b.icon:SetTexture((GetInventoryItemTexture and GetInventoryItemTexture("player",slot[2])) or "Interface\\Icons\\INV_Misc_QuestionMark")
    end
end
ns.UpdateCharacterPanel=updateCharacterPanel
function ns.AttachCharacterPanel()
    if _G.RetSimBridgeDB then return end -- The personal panel retains its place until handoff.
    if not CharacterFrame or characterHooked then return end
    characterHooked=true
    local panel=CreateFrame("Frame","GuildSimBetaCharacterPanel",CharacterFrame,"BackdropTemplate");ns.characterPanel=panel
    panel:SetWidth(320);panel:SetClampedToScreen(true);panel:SetFrameStrata("DIALOG")
    surface(panel)
    text(panel,"GuildSimBeta  ·  My gear",14,-18,270,"GameFontNormal")
    local close=CreateFrame("Button",nil,panel,"UIPanelCloseButton");close:SetPoint("TOPRIGHT",-4,-4)
    panel.baseline=text(panel,"",14,-43,290,"GameFontNormalLarge")
    panel.reference=text(panel,"",14,-72,290,"GameFontNormalSmall")
    panel.coverage=text(panel,"",14,-92,290,"GameFontNormalSmall");panel.coverage:SetTextColor(.65,.69,.75)
    local details=CreateFrame("Button",nil,panel);details:SetPoint("TOPLEFT",12,-40);details:SetSize(290,48)
    details:SetScript("OnEnter",function()
        if not GameTooltip then return end
        GameTooltip:SetOwner(panel,"ANCHOR_RIGHT");GameTooltip:AddLine("Reference setup",1,.82,.35)
        GameTooltip:AddLine(ns.itemResults and ns.itemResults.comparisonLabel or "No reference loaded",.9,.9,.9,true)
        GameTooltip:AddLine("Catalog DPS uses these trinkets. Your worn trinkets can differ.",.7,.75,.82,true);GameTooltip:Show()
    end)
    details:SetScript("OnLeave",function()if GameTooltip then GameTooltip:Hide()end end)
    panel.rows={}
    for i,slot in ipairs(browserSlots) do
        local index=i;local b=CreateFrame("Button",nil,panel)
        b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetPoint("LEFT")
        b.selected=b:CreateTexture(nil,"BACKGROUND");b.selected:SetAllPoints();b.selected:SetColorTexture(.31,.22,.065,1);b.selected:Hide()
        b.slot=text(b,slot[1],29,-4,63,"GameFontNormalSmall");b.slot:SetTextColor(.62,.66,.72)
        b.item=text(b,"",94,-4,200)
        b:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight")
        b:SetScript("OnClick",function()ns.ShowGearBrowser("gear",index,true)end)
        b:SetScript("OnEnter",function()if b.link then tooltipItem(b,b.link)end end)
        b:SetScript("OnLeave",function()if GameTooltip then GameTooltip:Hide()end end)
        panel.rows[i]=b
    end
    local pairsButton=button(panel,"Trinket pairs",12,-1,142,function()ns.ShowGearBrowser("pairs",nil,true)end)
    pairsButton:ClearAllPoints();pairsButton:SetPoint("BOTTOMLEFT",12,12)
    local controls=button(panel,"Sim status",164,-1,142,function()ns.ShowProgress()end)
    controls:ClearAllPoints();controls:SetPoint("BOTTOMRIGHT",-12,12)
    local toggle=CreateFrame("Button","GuildSimBetaCharacterToggle",CharacterFrame,"UIPanelButtonTemplate")
    toggle:SetPoint("TOPRIGHT",CharacterFrame,"TOPRIGHT",-42,-8);toggle:SetSize(76,22);toggle:SetText("GuildSimBeta")
    toggle:SetScript("OnClick",function()
        if panel:IsShown() then panel:Hide() else updateCharacterPanel();panel:Show() end
    end)
    CharacterFrame:HookScript("OnShow",function()updateCharacterPanel();panel:Show()end)
    CharacterFrame:HookScript("OnHide",function()panel:Hide();if browser and browser.docked then browser:Hide()end end)
    CharacterFrame:HookScript("OnSizeChanged",function()updateCharacterPanel()end)
    if CharacterFrame:IsShown() then updateCharacterPanel();panel:Show() else panel:Hide() end
end
local dockEvents=CreateFrame("Frame")
for _,event in ipairs({"PLAYER_LOGIN","ADDON_LOADED","PLAYER_EQUIPMENT_CHANGED","PLAYER_TALENT_UPDATE","PLAYER_LEVEL_UP"}) do dockEvents:RegisterEvent(event) end
dockEvents:SetScript("OnEvent",function()
    ns.AttachCharacterPanel()
    if not ns.characterPanel or not ns.characterPanel:IsShown() or dockPending then return end
    dockPending=true
    if C_Timer and C_Timer.After then C_Timer.After(.15,updateCharacterPanel) else updateCharacterPanel() end
end)
ns.AttachCharacterPanel()
