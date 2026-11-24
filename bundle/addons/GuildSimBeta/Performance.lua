if select(2,UnitClass("player"))~="PALADIN" then return end
local _, ns = ...
local running=false
local function say(text)print("|cffead36cRet Sim performance:|r "..text)end
local function errors()
    local out={}
    if not BugGrabber or not BugGrabber.GetDB then return out end
    local data=BugGrabber:GetDB();data=data and (data.errors or data)
    local session=BugGrabber.GetSessionId and BugGrabber:GetSessionId()
    for _, error in pairs(data or {}) do
        if type(error)=="table" and error.message and (not session or error.session==session) then out[error.message]=error.counter or 1 end
    end
    return out
end
function ns.Performance()
    if running then say("A 15-second sample is already running.");return end
    local api=C_AddOnProfiler;local enums=Enum and Enum.AddOnProfilerMetric
    local metric=enums and enums.RecentAverageTime
    local available=api and api.GetAddOnMetric and metric and (not api.IsEnabled or api.IsEnabled())
    local addons={}
    if available and C_AddOns and C_AddOns.GetNumAddOns then
        for i=1,C_AddOns.GetNumAddOns() do
            local name=C_AddOns.GetAddOnInfo(i)
            if name and C_AddOns.IsAddOnLoaded(name) then addons[#addons+1]=name end
        end
    end
    local startErrors=errors();local totals={};local fps={};local n=0
    running=true
    say("Sampling for 15 seconds. Play normally or hover the items that cause the slowdown.")
    local function sample()
        n=n+1;fps[n]=GetFramerate()
        if available and api.GetTopKAddOnsForMetric then
            local ok,rows=pcall(api.GetTopKAddOnsForMetric,metric,20)
            if ok and type(rows)=="table" then
                for _,row in ipairs(rows)do
                    if type(row.addOnName)=="string" and type(row.metricValue)=="number" then totals[row.addOnName]=(totals[row.addOnName] or 0)+row.metricValue end
                end
            end
        elseif available then
            for _,name in ipairs(addons) do
                local ok,value=pcall(api.GetAddOnMetric,name,metric)
                if ok and type(value)=="number" then totals[name]=(totals[name] or 0)+value end
            end
        end
        if n<15 then C_Timer.After(1,sample);return end
        local ranked={};for name,total in pairs(totals)do ranked[#ranked+1]={name=name,recentCpuMs=total/n}end
        table.sort(ranked,function(a,b)return a.recentCpuMs>b.recentCpuMs end)
        local min,sum=math.huge,0;for _,value in ipairs(fps)do min=math.min(min,value);sum=sum+value end
        local newErrors={};for message,count in pairs(errors())do
            local difference=count-(startErrors[message] or 0)
            if difference>0 then newErrors[#newErrors+1]={message=message,count=difference}end
        end
        GuildSimBetaDB=GuildSimBetaDB or {}
        GuildSimBetaDB.performance={time=time(),fpsAverage=sum/n,fpsMinimum=min,addons=ranked,newErrors=newErrors,cpuAvailable=available and #ranked>0 or false}
        running=false
        say(string.format("FPS average %.1f, minimum %.1f. %d error types occurred during the sample.",sum/n,min,#newErrors))
        if #ranked>0 then
            for i=1,math.min(8,#ranked)do say(string.format("%s: sampled recent CPU %.3f ms",ranked[i].name,ranked[i].recentCpuMs))end
        else say("Native addon CPU metrics are unavailable; no CPU ranking was guessed. Script profiling settings were left unchanged.")end
        say("/reload saves the sample so the local diagnostic can read it.")
    end
    C_Timer.After(1,sample)
end
