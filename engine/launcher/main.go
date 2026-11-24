// Stable launcher and trusted signature verifier; versioned helpers update beside it.
package main
import("encoding/json";"flag";"fmt";"os";"os/exec";"path/filepath";"strings";"syscall";"time";"guildsim/beta/trust")
type Active struct{Version string `json:"version"`; Previous string `json:"previous,omitempty"`;Sequence int `json:"sequence"`;Failed string `json:"failedVersion,omitempty"`}
func atomic(path string,data []byte) error {tmp:=path+".pending";if e:=os.WriteFile(tmp,data,0600);e!=nil{return e};return replace(tmp,path)}
func main(){verify:=flag.String("verify-manifest","","manifest to verify");sig:=flag.String("signature","","detached signature");background:=flag.Bool("background",false,"start hidden");rootFlag:=flag.String("root","","application directory");flag.Parse()
 if *verify!="" {data,e:=os.ReadFile(*verify);if e!=nil{os.Exit(2)};signature,e:=os.ReadFile(*sig);if e!=nil{os.Exit(2)};if e=trust.Verify(data,string(signature));e!=nil{fmt.Fprintln(os.Stderr,e);os.Exit(3)};return}
 root:=*rootFlag;if root=="" {root=filepath.Join(os.Getenv("LOCALAPPDATA"),"GuildSimBeta")};root,_=filepath.Abs(root)
 path:=filepath.Join(root,"active.json");data,e:=os.ReadFile(path);if e!=nil{return};var active Active;if json.Unmarshal(data,&active)!=nil{return}
 launch:=func(version string)bool{
  if strings.ContainsAny(version,"/\\:")||version==""||version==".."{return false}
  base:=filepath.Join(root,"releases",version);exe:=filepath.Join(base,"GuildSim Helper.exe");health:=filepath.Join(root,"health-"+version+".json");os.Remove(health)
  args:=[]string{"--health-file",health};if *background{args=append(args,"--background")}
  if _,e:=os.Stat(filepath.Join(root,"settings.json"));os.IsNotExist(e){args=append(args,"--first-run")}
  cmd:=exec.Command(exe,args...);cmd.Dir=base;cmd.SysProcAttr=&syscall.SysProcAttr{HideWindow:true,CreationFlags:0x08000000};if cmd.Start()!=nil{return false}
  for n:=0;n<60;n++ {if _,e:=os.Stat(health);e==nil{return true};time.Sleep(500*time.Millisecond)}
  // Only terminate the child we just launched, after a failed startup handshake.
  cmd.Process.Kill();return false
 }
 if launch(active.Version){return}
 if active.Previous!=""&&active.Previous!=active.Version {old:=active.Previous;active.Failed=active.Version;active.Version=old;active.Previous="";data,_=json.Marshal(active);atomic(path,data);launch(old)}
}
