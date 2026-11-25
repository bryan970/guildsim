if select(2,UnitClass("player"))~="PRIEST" then return end
local _, ns = ...
local GOLD={1,.79,.15};local MUTED={.64,.70,.77}
local slots={"Head","Neck","Shoulders","Back","Chest","Wrists","Hands","Waist","Legs","Feet","Ring 1","Ring 2","Trinket 1","Trinket 2","Main hand","Off hand","Relic / wand"}
local inventory={1,2,3,15,5,9,10,6,7,8,11,12,13,14,16,17,18}
local mobs={"Unspecified","Beast","Demon","Dragonkin","Elemental","Giant","Humanoid","Mechanical","Undead"}
local families={"Unspecified","Naga","Satyr","Aquatic","Earth elemental","Fire elemental","Mountain giant","Swine","Plant","Troll","Orc","Ogre","Wolf","Worgen","Murloc","Furbolg","Dwarf","Dinosaur","Serpentine"}
local assignments={"group","tank","burst"}
local assignmentNames={group="Group healing",tank="Tank healing",burst="Burst recovery"}
local panel,browser,render,selected= nil,nil,nil,0
local mode,page,search="gear",1,""
local docked=false
local function db()
 GuildSimBetaDB=GuildSimBetaDB or {};GuildSimBetaDB.characters=GuildSimBetaDB.characters or {}
 local guid=UnitGUID("player");GuildSimBetaDB.characters[guid]=GuildSimBetaDB.characters[guid] or {pool={},excluded={},mobType=0,creatureFamily=0}
 return GuildSimBetaDB.characters[guid]
end
local function text(parent,size,color)
 local t=parent:CreateFontString(nil,"OVERLAY","GameFontNormal");t:SetFont(t:GetFont(),size or 12);t:SetJustifyH("LEFT")
 t:SetTextColor(unpack(color or { .9,.92,.95 }));return t
end
local function skin(f)
 if f.SetBackdrop then f:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Tooltips\\UI-Tooltip-Border",tile=false,edgeSize=12,insets={left=3,right=3,top=3,bottom=3}});f:SetBackdropColor(.018,.023,.032,.99);f:SetBackdropBorderColor(.48,.39,.20,1) end
end
local function frame(name,w,h,parent)
 local f=CreateFrame("Frame",name,parent or UIParent,BackdropTemplateMixin and "BackdropTemplate" or nil);f:SetSize(w,h);skin(f);f:SetClampedToScreen(true);f:SetFrameStrata("DIALOG");f:EnableMouse(true)
 f:SetMovable(true);f:RegisterForDrag("LeftButton");f:SetScript("OnDragStart",f.StartMoving);f:SetScript("OnDragStop",f.StopMovingOrSizing)
 local close=CreateFrame("Button",nil,f,"UIPanelCloseButton");close:SetPoint("TOPRIGHT",-2,-2);close:SetScript("OnClick",function()f:Hide()end);return f
end
local function button(parent,label,w,x,y,action)
 local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate");b:SetSize(w,24);b:SetPoint("TOPLEFT",x,y);b:SetText(label);b:SetScript("OnClick",action);return b
end
local function hint(message)print("|cffffcc33GuildSim Beta:|r "..message)end
local function talentSignature()
 if not GetNumTalentTabs or not GetNumTalents or not GetTalentInfo then return nil end
 local out={};for tree=1,GetNumTalentTabs()do for index=1,GetNumTalents(tree)do local rank=select(5,GetTalentInfo(tree,index));table.insert(out,tostring(rank or 0))end;table.insert(out,"-")end
 return table.concat(out)
end
local function capture()
 local exporter=WowSimsExporter
 if LibStub then local lib=LibStub("AceAddon-3.0",true);exporter=(lib and lib:GetAddon("WowSimsExporter",true))or exporter end
 if not exporter or not exporter.BuildExport then hint("WowSimsExporter is required. Install it with the desktop helper.");return end
 local ok,result=pcall(exporter.BuildExport,exporter,false,false)
 if not ok or not result then hint("Character capture failed; use /wse to check the exporter.");return end
 local state=db();state.items={}
 for _,slot in ipairs(inventory)do local link=GetInventoryItemLink("player",slot);if link then table.insert(state.items,link)end end
 local num=(C_Container and C_Container.GetContainerNumSlots) or GetContainerNumSlots
 local linkfn=(C_Container and C_Container.GetContainerItemLink) or GetContainerItemLink
 if num and linkfn then for bag=0,4 do for slot=1,num(bag)do local link=linkfn(bag,slot);if link then table.insert(state.items,link)end end end end
 state.talentSignature=talentSignature();state.requestedAt=time();hint("Capture ready. Use /reload to save it. Keep the desktop helper open; /reload again when it says Ready.")
 if render then render()end
end
local function spec(link)
 local body=tostring(link or ""):match("item:([%-%d:]+)");if not body then return 0,0,0 end
 local f={};for value in (body..":"):gmatch("(.-):")do table.insert(f,value)end
 return tonumber(f[1])or 0,tonumber(f[2])or 0,tonumber(f[7])or 0
end
local function payload()return ns.results and ns.results[UnitGUID("player")]end
local function fresh(p)
 if not p or p.guid~=UnitGUID("player")then return false,"No results for this character. Update sims to begin."end
 if p.version~="0.2.0-beta.4" then return false,"Results are from another beta version. Update sims." end
 if time()-(p.generated or 0)>86400 then return false,"Results are over 24 hours old. Update sims."end
 local state=db()
 if (p.mobType or 0)~=(state.mobType or 0)or(p.creatureFamily or 0)~=(state.creatureFamily or 0)then return false,"Encounter changed. Update sims for this target."end
 if p.healingScenario and (p.healingScenario.assignment~=(state.healingAssignment or"group")or p.healingScenario.duration~=(state.healingDuration or 180))then return false,"Healing assignment changed. Update sims for this fight."end
 for index,slot in ipairs(inventory)do
  local id,enchant,suffix=spec(GetInventoryItemLink("player",slot));local old=(p.equipped or {})[index]or{}
  if id~=(old.id or 0)or enchant~=(old.enchant or 0)or suffix~=(old.randomSuffix or 0)then return false,"Gear changed. Update sims to refresh personal comparisons."end
 end
 if p.talentSignature and talentSignature()~=p.talentSignature then return false,"Talents changed. Update sims."end
 if (state.requestedAt or 0)>(p.generated or 0)then return false,"Capture queued. Wait for the helper, then /reload."end
 return true
end
local function quality(t,item)
 local color=ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[item.quality or 1]
 if color then t:SetTextColor(color.r,color.g,color.b)else t:SetTextColor(.8,.65,1)end
end
local function itemname(item)
 if not item then return "Empty"end
 local get=(C_Item and C_Item.GetItemInfo)or GetItemInfo
 return item.name or (get and get(item.id))or("Item "..tostring(item.id))
end
local function tooltip(row)
 if not row.data then return end
 local data=row.data;GameTooltip:SetOwner(row,"ANCHOR_LEFT")
 if #data.items==1 then
  local it=data.items[1];GameTooltip:SetHyperlink("item:"..it.id..":"..(it.enchant or 0)..":0:0:0:0:"..(it.randomSuffix or 0))
 else GameTooltip:AddLine(itemname(data.items[1]).." + "..itemname(data.items[2]),1,.8,.2,true)end
 GameTooltip:AddLine(" ");GameTooltip:AddLine(data.error or(data.missingEffects and next(data.missingEffects)and"Partial model: upstream lists missing item effects"or"Native engine result"),1,.8,.2,true)
 for id,gaps in pairs(data.missingEffects or {})do for _,note in ipairs(gaps)do GameTooltip:AddLine("Item "..id..": "..note,1,.55,.3,true)end end
 for _,item in ipairs(data.items)do GameTooltip:AddLine(item.source or"Acquisition source unverified",.8,.84,.9,true)end
 if data.stats then for _,key in ipairs({"HealingPower","Mana","Intellect","Spirit","MP5","SpellCritPercent"})do if data.stats[key]then GameTooltip:AddLine(key..": "..string.format("%.2f",data.stats[key]),.8,.84,.9)end end end
 if data.healingModel then
  if data.screening then GameTooltip:AddLine("Screening estimate; leading catalog candidates receive more confirmation fights.",1,.85,.4,true)end
  GameTooltip:AddLine(string.format("Effective healing: %.1f HPS",data.effectiveHps or 0),.5,1,.7)
  GameTooltip:AddLine(string.format("Consumed shields: %.1f HPS",data.absorbHps or 0),.5,.8,1)
  GameTooltip:AddLine(string.format("Overhealing: %.1f HPS (excluded)",data.overhealHps or 0),.8,.8,.8)
  GameTooltip:AddLine(string.format("Assignment survival: %.1f%% · Mana remaining: %.0f",100*(data.survival or 0),data.manaRemaining or 0),1,.85,.4,true)
  GameTooltip:AddLine(string.format("%d fights · approximately ±%.1f HPS sampling margin",data.iterations or 0,data.meanError95 or 0),.8,.84,.9,true)
  GameTooltip:AddLine("Stationary assigned damage, native spell priorities and item effects. This does not simulate an entire raid or score dispels and movement.",.8,.84,.9,true)
 end
 GameTooltip:Show()
end
local function build()
 if panel then return end
 panel=frame("GuildSimBetaCharacterPanel",280,492);panel:SetPoint("CENTER",UIParent,"CENTER",-350,0)
 panel.title=text(panel,17,GOLD);panel.title:SetPoint("TOPLEFT",14,-16);panel.title:SetText("GuildSim · My gear")
 panel.summary=text(panel,13);panel.summary:SetPoint("TOPLEFT",14,-47);panel.summary:SetWidth(250)
 panel.sub=text(panel,11,MUTED);panel.sub:SetPoint("TOPLEFT",14,-72);panel.sub:SetWidth(250)
 panel.slots={}
 for i=1,17 do
  local b=CreateFrame("Button",nil,panel);b:SetSize(254,20);b:SetPoint("TOPLEFT",12,-104-(i-1)*20)
  b.icon=b:CreateTexture(nil,"ARTWORK");b.icon:SetSize(18,18);b.icon:SetPoint("LEFT",0,0)
  b.label=text(b,11,MUTED);b.label:SetPoint("LEFT",b.icon,"RIGHT",5,0);b.label:SetWidth(62);b.label:SetText(slots[i])
  b.name=text(b,11);b.name:SetPoint("LEFT",b.label,"RIGHT",4,0);b.name:SetWidth(164)
  b:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight");b:SetScript("OnClick",function()selected=i-1;mode=(i==13 or i==14)and"pair"or"gear";page=1;browser:Show();render()end)
  panel.slots[i]=b
 end
 button(panel,"Trinket pairs",122,12,-453,function()mode="pair";page=1;browser:Show();render()end)
 button(panel,"Update sims",122,144,-453,capture)
 browser=frame("GuildSimBetaBrowser",800,586);browser:SetPoint("LEFT",panel,"RIGHT",8,-47)
 browser.title=text(browser,19,GOLD);browser.title:SetPoint("TOPLEFT",18,-17)
 browser.subtitle=text(browser,11,MUTED);browser.subtitle:SetPoint("TOPLEFT",18,-46);browser.subtitle:SetWidth(750)
 button(browser,"Gear",95,18,-82,function()mode="gear";page=1;render()end)
 button(browser,"Trinket pairs",120,120,-82,function()mode="pair";page=1;render()end)
 button(browser,"Update sims",125,520,-16,capture)
 button(browser,"Load results",125,650,-16,function()hint("Use /reload to load the desktop helper's latest results.")end)
 browser.mob=button(browser,"",180,250,-82,function()local state=db();if select(2,UnitClass("player"))=="PRIEST"then local current=state.healingAssignment or"group";for i,v in ipairs(assignments)do if v==current then state.healingAssignment=assignments[i%#assignments+1];break end end else state.mobType=((state.mobType or 0)+1)%#mobs end;page=1;render()end)
 browser.family=button(browser,"",220,440,-82,function()local state=db();if select(2,UnitClass("player"))=="PRIEST"then state.healingDuration=(state.healingDuration or 180)==180 and 300 or 180 else state.creatureFamily=((state.creatureFamily or 0)+1)%#families end;page=1;render()end)
 browser.search=CreateFrame("EditBox",nil,browser,"InputBoxTemplate");browser.search:SetSize(300,22);browser.search:SetPoint("TOPLEFT",24,-120);browser.search:SetAutoFocus(false)
 browser.search:SetScript("OnTextChanged",function(self)search=self:GetText():lower();page=1;if render then render()end end);browser.search:SetScript("OnEscapePressed",function(self)self:ClearFocus()end)
 local label=text(browser,10,MUTED);label:SetPoint("TOPLEFT",338,-123);label:SetText("Search name / source")
 browser.pool=CreateFrame("EditBox",nil,browser,"InputBoxTemplate");browser.pool:SetSize(84,22);browser.pool:SetPoint("TOPLEFT",500,-120);browser.pool:SetAutoFocus(false);browser.pool:SetNumeric(true)
 button(browser,"Add ID",88,590,-120,function()local id=tonumber(browser.pool:GetText());if id then local state=db();state.pool[id]=true;state.excluded[id]=nil;hint("Added item "..id.." to the pool. Update sims to analyze it.")end end)
 button(browser,"Exclude ID",92,684,-120,function()local id=tonumber(browser.pool:GetText());if id then local state=db();state.excluded[id]=true;state.pool[id]=nil;hint("Excluded item "..id.." from the pool. Update sims to apply.")end end)
 local head=text(browser,12,GOLD);head:SetPoint("TOPLEFT",55,-163);head:SetText("Item / pair")
 browser.metric=text(browser,12,GOLD);browser.metric:SetPoint("TOPLEFT",500,-163)
 local delta=text(browser,12,GOLD);delta:SetPoint("TOPLEFT",655,-163);delta:SetText("Change")
 browser.rows={}
 for i=1,10 do
  local row=CreateFrame("Button",nil,browser);row:SetSize(762,31);row:SetPoint("TOPLEFT",18,-185-(i-1)*32)
  local bg=row:CreateTexture(nil,"BACKGROUND");bg:SetAllPoints();bg:SetColorTexture(.075,.095,.13,i%2==0 and .5 or .2)
  row.icon=row:CreateTexture(nil,"ARTWORK");row.icon:SetSize(27,27);row.icon:SetPoint("LEFT",2,0)
  row.name=text(row,12);row.name:SetPoint("TOPLEFT",37,-2);row.name:SetWidth(420)
  row.note=text(row,10,MUTED);row.note:SetPoint("TOPLEFT",37,-18);row.note:SetWidth(420)
  row.value=text(row,12);row.value:SetPoint("LEFT",482,0);row.value:SetWidth(145)
  row.gain=text(row,12);row.gain:SetPoint("RIGHT",-12,0);row.gain:SetJustifyH("RIGHT")
  row:SetScript("OnEnter",tooltip);row:SetScript("OnLeave",function()GameTooltip:Hide()end)
  browser.rows[i]=row
 end
 browser.empty=text(browser,14,MUTED);browser.empty:SetPoint("TOPLEFT",50,-225);browser.empty:SetWidth(700)
 button(browser,"Previous",95,18,-516,function()page=math.max(1,page-1);render()end)
 button(browser,"Next",95,122,-516,function()page=page+1;render()end)
 browser.count=text(browser,11,MUTED);browser.count:SetPoint("TOPLEFT",232,-522)
 browser.footer=text(browser,10,MUTED);browser.footer:SetPoint("TOPLEFT",18,-553);browser.footer:SetWidth(760)
 table.insert(UISpecialFrames,"GuildSimBetaBrowser");table.insert(UISpecialFrames,"GuildSimBetaCharacterPanel")
 panel:Hide();browser:Hide()
end
render=function()
 if not panel then return end
 local p=payload();local valid,why=fresh(p);local state=db();local priest=select(2,UnitClass("player"))=="PRIEST"
 local healing=priest and p and p.baseline and p.baseline.healingModel
 panel.summary:SetText(healing and string.format("%.1f useful HPS · equipped",p.baseline.usefulHps or 0)or priest and"Discipline · awaiting healing sim"or(p and p.baseline and p.baseline.dps and string.format("%.1f DPS · equipped",p.baseline.dps)or"Retribution · awaiting capture"))
 panel.sub:SetText(valid and(healing and string.format("%s · %.0f%% survival",assignmentNames[p.healingScenario.assignment],100*(p.baseline.survival or 0))or priest and"Older stats result · update sims"or"Native DPS · reference catalog")or"Update sims to refresh")
 for i,b in ipairs(panel.slots)do local link=GetInventoryItemLink("player",inventory[i]);local id=spec(link);local get=(C_Item and C_Item.GetItemInfo)or GetItemInfo;local name,_,q,_,_,_,_,_,_,icon=get(id);b.name:SetText(name or(id~=0 and("Item "..id)or"Empty"));b.icon:SetTexture(icon or"Interface\\Icons\\INV_Misc_QuestionMark");if q and ITEM_QUALITY_COLORS[q]then local c=ITEM_QUALITY_COLORS[q];b.name:SetTextColor(c.r,c.g,c.b)end end
 browser.title:SetText(mode=="pair"and"Your trinket combinations"or(slots[selected+1].." comparisons"))
 local reference=p and p.reference and p.reference.dps
 browser.subtitle:SetText(healing and"Useful HPS = effective healing + consumed shields. Catalog: fixed reference trinkets; pairs: equipped gear."or priest and"Update sims to run the selected healing assignment."or("Catalog uses fixed reference trinkets"..(reference and string.format(" · %.1f reference DPS",reference)or"")..". Pairs use exported gear."))
 browser.mob:SetText(priest and assignmentNames[state.healingAssignment or"group"]or("Type: "..mobs[(state.mobType or 0)+1]));browser.family:SetText(priest and string.format("Fight: %d minutes",(state.healingDuration or 180)/60)or("Family: "..families[(state.creatureFamily or 0)+1]))
 browser.metric:SetText(healing and"Useful HPS / survival"or priest and"Healing power / Mana"or"Sim DPS")
 local rows={}
 if valid then for _,row in ipairs(p.rows or{})do
  local match=(row.kind==mode or(mode=="pair"and row.kind=="pair"))and(mode=="pair"or row.slot==selected)
  local hay="";for _,it in ipairs(row.items or{})do hay=hay..itemname(it).." "..(it.source or"")end
  if match and(search==""or hay:lower():find(search,1,true))then table.insert(rows,row)end
 end end
 -- Pair orientations are simulated separately; retain the better slot order in the pair list.
 local function better(a,b)
  if healing then
   local aliveA,aliveB=a.survival or 0,b.survival or 0
   if (aliveA>=.99)~=(aliveB>=.99)then return aliveA>=.99 end
   if aliveA<.99 and aliveB<.99 and aliveA~=aliveB then return aliveA>aliveB end
   return(a.usefulHps or-1)>(b.usefulHps or-1)
  end
  if priest then return table.concat({itemname(a.items[1]),itemname(a.items[2])})<table.concat({itemname(b.items[1]),itemname(b.items[2])})end
  return(a.dps or-1)>(b.dps or-1)
 end
 if mode=="pair"then local best={};for _,row in ipairs(rows)do local a,b=row.items[1],row.items[2];local keys={a.id..":"..(a.randomSuffix or 0),b.id..":"..(b.randomSuffix or 0)};table.sort(keys);local key=table.concat(keys,"+");local old=best[key];if not old or better(row,old)then best[key]=row end end;rows={};for _,row in pairs(best)do table.insert(rows,row)end end
 table.sort(rows,better)
 local pages=math.max(1,math.ceil(#rows/10));page=math.min(page,pages)
 for i,row in ipairs(browser.rows)do local data=rows[(page-1)*10+i];row.data=data
  if data then
   row:Show();row.icon:SetTexture("Interface\\Icons\\"..(data.items[1].icon or"INV_Misc_QuestionMark"))
   row.name:SetText(itemname(data.items[1])..(data.items[2]and(" + "..itemname(data.items[2]))or""));quality(row.name,data.items[1])
   row.note:SetText(data.error or(data.missingEffects and next(data.missingEffects)and(data.screening and"Partial model · screening estimate"or"Partial model · hover for missing effects")or(data.screening and"Screening estimate · "or"")..(data.items[1].source or"Source unverified")))
   local base=(mode=="pair"and p.baseline or p.reference)or{}
   if data.error then row.value:SetText("Unavailable");row.gain:SetText("")
   elseif healing then
    local gain=(data.usefulHps or 0)-(base.usefulHps or 0);local margin=math.sqrt((data.meanError95 or 0)^2+(base.meanError95 or 0)^2)
    row.value:SetText(string.format("%.1f / %.0f%%",data.usefulHps or 0,100*(data.survival or 0)))
    row.gain:SetText(math.abs(gain)<=margin and"≈ tied"or string.format("%+.1f HPS",gain));row.gain:SetTextColor(.45,.9,.8)
   elseif priest then row.value:SetText(string.format("%.0f / %.0f",data.stats.HealingPower or 0,data.stats.Mana or 0));row.gain:SetText(string.format("%+.0f HP",(data.stats.HealingPower or 0)-(base.stats and base.stats.HealingPower or 0)));row.gain:SetTextColor(.78,.83,.9)
   else local gain=(data.dps or 0)-(base.dps or 0);row.value:SetText(string.format("%.1f",data.dps));row.gain:SetText(string.format("%+.1f",gain));if gain>=0 then row.gain:SetTextColor(.15,1,.55)else row.gain:SetTextColor(1,.40,.35)end end
  else row:Hide()end
 end
 browser.empty:SetText(not valid and why or(#rows==0 and"No comparisons in this view. Capture bags or enable the full catalog in the helper."or""))
 browser.count:SetText(string.format("%d results · Page %d / %d",#rows,page,pages)..(p and not p.complete and" · Still simulating"or""))
 browser.footer:SetText("WoWSims Forever v1.0.4 · "..(healing and"Declared assignment · 99% survival gate, then useful HPS. Hover for mana, overhealing, sampling and model details."or priest and"Older stats result: update sims for native healing comparisons."or"DPS varies with race, talents, buffs and target. Small gains can fall within sampling error."))
end
local function show()
 build();docked=false;panel:Show();browser:Show();render()
end
SLASH_GUILDSIMBETA1="/guildsim";SLASH_GUILDSIMBETA2="/gsim"
SlashCmdList.GUILDSIMBETA=function(input)
 local id=input:match("^pool%s+(%d+)$");if id then db().pool[tonumber(id)]=true;db().excluded[tonumber(id)]=nil;hint("Added to pool. Update sims to compare.");return end
 if input=="update"then capture();return end
 show()
end
local events=CreateFrame("Frame");events:RegisterEvent("PLAYER_LOGIN");events:RegisterEvent("PLAYER_EQUIPMENT_CHANGED");events:RegisterEvent("PLAYER_TALENT_UPDATE")
events:SetScript("OnEvent",function(_,event)
 if event=="PLAYER_LOGIN"then
  build()
  if CharacterFrame then
   CharacterFrame:HookScript("OnShow",function()
    -- Coexistence: the personal RetSim panel retains its automatic character-pane position.
    if _G.RetSimBridgeDB then return end
    docked=true;panel:ClearAllPoints();panel:SetPoint("TOPLEFT",CharacterFrame,"TOPRIGHT",6,0);panel:Show();render()
   end)
   CharacterFrame:HookScript("OnHide",function()panel:Hide();if docked then browser:Hide()end end)
  end
 elseif panel and panel:IsShown()then render()end
end)
