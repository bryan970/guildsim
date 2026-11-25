// Local adapter around the unmodified WoWSims Forever simulation APIs.
// Built inside the pinned source snapshot, with --tags=with_db.
package main

import (
 "encoding/json"
 "flag"
 "fmt"
 "os"
 "path/filepath"
 "runtime"
 "strings"
 "time"

 "github.com/wowsims/forever/sim"
 "github.com/wowsims/forever/sim/core"
 "github.com/wowsims/forever/sim/core/proto"
 "github.com/wowsims/forever/sim/siml"
 gp "google.golang.org/protobuf/proto"
 "google.golang.org/protobuf/encoding/protojson"
)

type Export struct {
 Flavor string `json:"flavor"`
 Name string `json:"name"`
 ID string `json:"id"`
 Realm string `json:"realm"`
 Race string `json:"race"`
 Class string `json:"class"`
 Level int `json:"level"`
 Talents string `json:"talents"`
 Gear json.RawMessage `json:"gear"`
 Professions []struct{Name string `json:"name"`} `json:"professions"`
}
type Scenario struct {
 Name string `json:"name"`
 Duration float64 `json:"duration"`
 TargetLevel int32 `json:"target_level"`
 RaidBuffs json.RawMessage `json:"raid_buffs"`
 PartyBuffs json.RawMessage `json:"party_buffs"`
 Debuffs json.RawMessage `json:"debuffs"`
 IndividualBuffs json.RawMessage `json:"individual_buffs"`
 Consumables json.RawMessage `json:"consumables"`
 TargetGear json.RawMessage `json:"target_gear"`
 TargetTalents string `json:"target_talents"`
 MinimumMeleeHit float64 `json:"minimum_melee_hit_percent"`
}
func must(err error) { if err!=nil { panic(err) } }
func raw(p gp.Message) json.RawMessage { b,e:=protojson.MarshalOptions{EmitUnpopulated:true}.Marshal(p);must(e);return b }
func load(b json.RawMessage,p gp.Message) {if len(b)>0 && string(b)!="null" {must(protojson.Unmarshal(b,p))}}
func main(){
 defer func(){if e:=recover();e!=nil {fmt.Fprintln(os.Stderr,"SIM FAILED:",e);os.Exit(1)}}()
 runtime.GOMAXPROCS(2)
 source:=flag.String("root","","WoWSims source root")
 charPath:=flag.String("character","","export JSON")
 scenarioPath:=flag.String("scenario","","scenario JSON")
 mode:=flag.String("mode","planning","planning or current (level 60 only)")
 iterations:=flag.Int("iterations",12500,"iterations per stat perturbation")
 noWeights:=flag.Bool("no-weights",false,"baseline-only diagnostic")
 batchPath:=flag.String("batch","","JSON array of labelled equipment sets; writes JSON lines")
 workers:=flag.Int("workers",2,"parallel batch simulations (1 to 4)")
 output:=flag.String("out","result.json","output JSON")
 flag.Parse()
 if *iterations<20 || *iterations>200000 {panic("iterations must be between 20 and 200000")}
 sim.RegisterAll()
 b,e:=os.ReadFile(*charPath);must(e);var ex Export;must(json.Unmarshal(b,&ex))
 if ex.Flavor!="forever" || !strings.EqualFold(ex.Class,"paladin") {panic("expected a Forever Paladin export")}
 var race proto.Race
 for _,r:=range core.ClassRaceCapabilities[proto.Class_ClassPaladin] {if strings.EqualFold(strings.TrimPrefix(r.String(),"Race"),strings.ReplaceAll(ex.Race," ","")) {race=r}}
 if race==proto.Race_RaceUnknown {panic("unsupported Paladin race")}
 if *mode!="planning" && *mode!="current" {panic("mode must be planning or current")}
 if *mode=="current" && ex.Level!=60 {panic("the upstream simulator models level 60 only; choose planning for a leveling character")}
 var sc Scenario;b,e=os.ReadFile(*scenarioPath);must(e);must(json.Unmarshal(b,&sc))
 if sc.Duration<30 || sc.TargetLevel<60 || sc.TargetLevel>63 {panic("invalid encounter duration or target level")}
 basePath:=filepath.Join(*source,"ui/specs/paladin/retribution")
 f,e:=siml.ReadFile(filepath.Join(basePath,"defaults.siml"));must(e)
 s:=gp.Clone(f.Settings).(*proto.IndividualSimSettings)
 p:=s.Player
 if p==nil || p.GetRetributionPaladin()==nil {panic("Ret preset missing")}
 p.Race=race;p.Class=proto.Class_ClassPaladin;p.Name=ex.Name
 p.Profession1=proto.Profession_ProfessionUnknown;p.Profession2=proto.Profession_ProfessionUnknown
 for i,v:=range ex.Professions { if i>1 {break}; val,ok:=proto.Profession_value[v.Name];if !ok {panic("unknown profession: "+v.Name)};if i==0{p.Profession1=proto.Profession(val)}else{p.Profession2=proto.Profession(val)} }
 if *mode=="current" {
  if ex.Talents=="" || ex.Talents=="--" {panic("export has no talents")}
  p.TalentsString=ex.Talents
  var g map[string]json.RawMessage;must(json.Unmarshal(ex.Gear,&g));delete(g,"version");gb,e:=json.Marshal(g);must(e)
  p.Equipment=&proto.EquipmentSpec{};must(protojson.Unmarshal(gb,p.Equipment))
 } else {
  if len(sc.TargetGear)>0 && string(sc.TargetGear)!="null" {p.Equipment=&proto.EquipmentSpec{};load(sc.TargetGear,p.Equipment)}
  if sc.TargetTalents!="" {p.TalentsString=sc.TargetTalents}
 }
 trees:=strings.Split(p.TalentsString,"-")
 if len(trees)!=3 || len(trees[2])!=17 || trees[2][16]!='1' {panic("this adapter requires Unsealed Wrath; select a matching level-60 build")}
 // Explicitly reset the raid/consumable assumptions inherited from the preset.
 s.RaidBuffs=&proto.RaidBuffs{};load(sc.RaidBuffs,s.RaidBuffs)
 s.PartyBuffs=&proto.PartyBuffs{};load(sc.PartyBuffs,s.PartyBuffs)
 s.Debuffs=&proto.Debuffs{};load(sc.Debuffs,s.Debuffs)
 p.Buffs=&proto.IndividualBuffs{};load(sc.IndividualBuffs,p.Buffs)
 p.Consumables=&proto.ConsumesSpec{};load(sc.Consumables,p.Consumables)
 p.EnableItemSwap=false;p.ItemSwap=nil
 p.InFrontOfTarget=false
 if p.Equipment==nil || len(p.Equipment.Items)>17 {panic("invalid equipment slot count")}
 for len(p.Equipment.Items)<17 {p.Equipment.Items=append(p.Equipment.Items,&proto.ItemSpec{})}
 for i,item:=range p.Equipment.Items {if item==nil {p.Equipment.Items[i]=&proto.ItemSpec{}}}
 apl,e:=siml.ReadFile(filepath.Join(basePath,"apls/default.apl.siml"));must(e)
 p.Rotation=apl.Rotation();p.Rotation.Type=proto.APLRotation_TypeAPL
 if p.Profession1!=proto.Profession_Enchanting && p.Profession2!=proto.Profession_Enchanting {
  for _,slot:=range []int{10,11}{if len(p.Equipment.Items)>slot && p.Equipment.Items[slot]!=nil {p.Equipment.Items[slot].Enchant=0}}
 }
 count:=0;var unknown []int32
 for _,item:=range p.Equipment.Items{if item!=nil && item.Id!=0 {count++;if core.GetItemByID(item.Id)==nil {unknown=append(unknown,item.Id)}}}
 if count<12 {panic("incomplete gear set; at least 12 equipped items are required")}
 if len(unknown)>0 {panic(fmt.Sprintf("items missing from this engine database: %v; refusing silent omissions",unknown))}
 equip:=core.ProtoToEquipment(p.Equipment)
 if equip.MainHand().ID==0 || equip.MainHand().HandType!=proto.HandType_HandTypeTwoHand {panic("expected a two-handed main-hand weapon")}
 s.Encounter.Duration=sc.Duration;s.Encounter.DurationVariation=0;s.Encounter.Targets=s.Encounter.Targets[:1]
 s.Encounter.Targets[0].Level=sc.TargetLevel
 s.Encounter.Targets[0].ParryHaste=false
 opts:=&proto.SimOptions{Iterations:int32(*iterations),RandomSeed:17012026}
 raid:=core.SinglePlayerRaidProto(p,s.PartyBuffs,s.RaidBuffs,s.Debuffs)
 req:=&proto.RaidSimRequest{Raid:raid,Encounter:s.Encounter,SimOptions:opts,Type:proto.SimType_SimTypeIndividual}
 if *batchPath!="" {
  if *workers<1 || *workers>4 {panic("batch workers must be between 1 and 4")}
  runtime.GOMAXPROCS(*workers)
  type Job struct {Label string `json:"label"`; Equipment json.RawMessage `json:"equipment"`; Consumables json.RawMessage `json:"consumables"`}
  var jobs []Job;b,e=os.ReadFile(*batchPath);must(e);must(json.Unmarshal(b,&jobs))
  stream,e:=os.Create(*output);must(e);defer stream.Close();encoder:=json.NewEncoder(stream)
  queue:=make(chan Job);rows:=make(chan map[string]any,*workers)
  for worker:=0;worker<*workers;worker++ {go func(){for job:=range queue {
   func(){
   defer func(){if failure:=recover();failure!=nil {rows<-map[string]any{"label":job.Label,"iterations":*iterations,"error":fmt.Sprint(failure)}}}()
   candidate:=gp.Clone(req).(*proto.RaidSimRequest)
   if len(job.Consumables)>0 {candidate.Raid.Parties[0].Players[0].Consumables=&proto.ConsumesSpec{};load(job.Consumables,candidate.Raid.Parties[0].Players[0].Consumables)}
   equipment:=&proto.EquipmentSpec{};load(job.Equipment,equipment)
   var missing []int32
   for _,item:=range equipment.Items {if item!=nil && item.Id!=0 && core.GetItemByID(item.Id)==nil {missing=append(missing,item.Id)}}
   row:=map[string]any{"label":job.Label,"iterations":*iterations}
   if len(missing)>0 {row["error"]=fmt.Sprintf("items missing from engine: %v",missing)} else {
    candidate.Raid.Parties[0].Players[0].Equipment=equipment
    if sc.MinimumMeleeHit>0 {
     computed:=core.ComputeStats(&proto.ComputeStatsRequest{Raid:candidate.Raid,Encounter:candidate.Encounter})
     if computed.ErrorResult!="" {row["error"]=computed.ErrorResult;rows<-row;return}
     hit:=computed.RaidStats.Parties[0].Players[0].FinalStats.PseudoStats[12]
     row["meleeHitPercent"]=hit
     if hit+0.000001<sc.MinimumMeleeHit {row["ineligible"]=true;rows<-row;return}
    }
    result:=core.RunRaidSim(candidate)
    if result.Error!=nil && result.Error.Message!="" {row["error"]=result.Error.Message} else {
     metrics:=result.GetRaidMetrics().GetDps()
     row["dps"]=metrics.GetAvg();row["stdev"]=metrics.GetStdev()
     row["secondsOom"]=result.RaidMetrics.Parties[0].Players[0].SecondsOomAvg
    }
   }
   rows<-row
   }()
  }}()}
  go func(){for _,job:=range jobs {queue<-job};close(queue)}()
  for index:=range jobs {
   must(encoder.Encode(<-rows))
   if (index+1)%25==0 || index==len(jobs)-1 {fmt.Fprintf(os.Stderr,"Batch: %d / %d\n",index+1,len(jobs))}
  }
  return
 }
 computed:=core.ComputeStats(&proto.ComputeStatsRequest{Raid:raid,Encounter:s.Encounter})
 if computed.ErrorResult!="" {panic(computed.ErrorResult)}
 if *mode=="planning" && sc.MinimumMeleeHit>0 && computed.RaidStats.Parties[0].Players[0].FinalStats.PseudoStats[12]+0.000001<sc.MinimumMeleeHit {panic("planning set is below the required melee hit cap")}
 fmt.Fprintln(os.Stderr,"Computing baseline:",*mode,sc.Name)
 baseline:=core.RunRaidSimConcurrent(req)
 if baseline.Error!=nil && baseline.Error.Message!="" {panic(baseline.Error.Message)}
 if baseline.GetRaidMetrics().GetDps().GetAvg()<=0 {panic("baseline did not deal damage")}
 report:=map[string]any{"mode":*mode,"scenario":sc.Name,"created":time.Now().UTC().Format(time.RFC3339),"export":ex,"simulatedLevel":60,"iterations":*iterations,"settings":raw(s),"request":raw(req),"baseline":raw(baseline),"characterStats":raw(computed)}
 if !*noWeights {
  sw:=&proto.StatWeightsRequest{Player:p,RaidBuffs:s.RaidBuffs,PartyBuffs:s.PartyBuffs,Debuffs:s.Debuffs,Encounter:s.Encounter,SimOptions:opts,EpReferenceStat:proto.Stat_StatAttackPower,HpsReferenceStat:proto.Stat_StatAttackPower,
   StatsToWeigh:[]proto.Stat{proto.Stat_StatStrength,proto.Stat_StatAgility,proto.Stat_StatIntellect,proto.Stat_StatSpirit,proto.Stat_StatSpellDamage,proto.Stat_StatHolyDamage,proto.Stat_StatSpellPiercing,proto.Stat_StatAttackPower,proto.Stat_StatHitRating,proto.Stat_StatCritRating,proto.Stat_StatHasteRating,proto.Stat_StatArmorPenetration,proto.Stat_StatExpertiseRating,proto.Stat_StatMP5},
   PseudoStatsToWeigh:[]proto.PseudoStat{proto.PseudoStat_PseudoStatMainHandDps}}
  ch:=make(chan *proto.ProgressMetrics,100)
  go core.StatWeightsAsync(sw,ch,"ret-local-weights")
  var weights *proto.StatWeightsResult
  last:=int32(-1)
  for v:=range ch {
   if v.CompletedSims!=last {last=v.CompletedSims;fmt.Fprintf(os.Stderr,"Stat sims: %d / %d\n",v.CompletedSims,v.TotalSims)}
   if v.FinalWeightResult!=nil {weights=v.FinalWeightResult;break}
  }
  if weights==nil {panic("no stat-weight result")}
  if weights.Error!=nil && weights.Error.Message!="" {panic(weights.Error.Message)}
  report["weights"]=raw(weights)
 }
 b,e=json.MarshalIndent(report,"","  ");must(e);must(os.WriteFile(*output,b,0644))
 fmt.Fprintf(os.Stderr,"Completed: %.2f DPS; %s\n",baseline.RaidMetrics.Dps.Avg,*output)
}
