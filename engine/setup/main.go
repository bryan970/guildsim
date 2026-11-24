// Single-download installer. Payload is authenticated before any release files are installed.
package main
import("archive/zip";"bytes";"crypto/sha256";"embed";"encoding/base64";"encoding/hex";"encoding/json";"flag";"fmt";"io";"os";"os/exec";"path/filepath";"strings";"syscall";"unicode/utf16";"guildsim/beta/trust")
//go:embed payload.zip update.json update.json.sig
var bundled embed.FS
type Release struct{Version string `json:"version"`;Sequence int `json:"sequence"`;SHA string `json:"sha256"`;Size int `json:"size"`}
func must(e error){if e!=nil{panic(e)}}
func quote(s string)string{return "'"+strings.ReplaceAll(s,"'","''")+"'"}
func hidden(c *exec.Cmd){c.SysProcAttr=&syscall.SysProcAttr{HideWindow:true,CreationFlags:0x08000000}}
func shortcuts(launcher string){
 script:="$w=New-Object -ComObject WScript.Shell; $a=$w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'GuildSim.lnk')); $a.TargetPath="+quote(launcher)+"; $a.WorkingDirectory="+quote(filepath.Dir(launcher))+"; $a.Save(); $b=$w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'GuildSim.lnk')); $b.TargetPath="+quote(launcher)+"; $b.WorkingDirectory="+quote(filepath.Dir(launcher))+"; $b.Save()"
 runes:=utf16.Encode([]rune(script));raw:=make([]byte,len(runes)*2);for i,v:=range runes {raw[2*i]=byte(v);raw[2*i+1]=byte(v>>8)}
 cmd:=exec.Command("powershell.exe","-NoProfile","-NonInteractive","-WindowStyle","Hidden","-EncodedCommand",base64.StdEncoding.EncodeToString(raw));hidden(cmd);cmd.Run()
}
func main(){defer func(){if e:=recover();e!=nil{user32:=syscall.NewLazyDLL("user32.dll");message,_:=syscall.UTF16PtrFromString(fmt.Sprint(e));title,_:=syscall.UTF16PtrFromString("GuildSim installation");user32.NewProc("MessageBoxW").Call(0,uintptr(unsafePointer(message)),uintptr(unsafePointer(title)),0x10);os.Exit(1)}}()
 extract:=flag.String("extract-to","","extract a verified portable release without installing shortcuts");flag.Parse()
 raw,e:=bundled.ReadFile("update.json");must(e);sig,e:=bundled.ReadFile("update.json.sig");must(e);must(trust.Verify(raw,string(sig)))
 var release Release;must(json.Unmarshal(raw,&release));if release.Version==""||strings.ContainsAny(release.Version,"/\\:"){panic("invalid release version")}
 payload,e:=bundled.ReadFile("payload.zip");must(e);sum:=sha256.Sum256(payload);if hex.EncodeToString(sum[:])!=release.SHA||len(payload)!=release.Size{panic("installer payload checksum failed")}
 root:=filepath.Join(os.Getenv("LOCALAPPDATA"),"GuildSimBeta");if *extract!=""{root=*extract};root,e=filepath.Abs(root);must(e);must(os.MkdirAll(root,0700))
 parent:=filepath.Join(root,"releases");if *extract!=""{parent=root};must(os.MkdirAll(parent,0700));stage,e:=os.MkdirTemp(parent,".install-");must(e)
 // The temporary directory is owned by this invocation, inside the selected install root.
 defer func(){if filepath.Dir(stage)==parent&&strings.HasPrefix(filepath.Base(stage),".install-"){os.RemoveAll(stage)}}()
 z,e:=zip.NewReader(bytes.NewReader(payload),int64(len(payload)));must(e);seen:=map[string]bool{};var expanded uint64
 prefix:="GuildSimBeta-"+release.Version+"/"
 for _,entry:=range z.File{
  name:=entry.Name;if !strings.HasPrefix(name,prefix){panic("invalid payload root")};name=strings.TrimPrefix(name,prefix);if name==""{continue}
  if strings.ContainsAny(name,"\\:")||strings.HasPrefix(name,"/"){panic("unsafe payload path")};for _,part:=range strings.Split(name,"/"){if part==".."||part=="."{panic("unsafe payload path")}}
  key:=strings.ToLower(strings.TrimSuffix(name,"/"));if seen[key]{panic("duplicate payload path")};seen[key]=true
  if entry.Mode()&os.ModeSymlink!=0{panic("linked payload file")};expanded+=entry.UncompressedSize64;if expanded>512*1024*1024{panic("payload too large")}
  dest:=filepath.Join(stage,filepath.FromSlash(name));if entry.FileInfo().IsDir(){must(os.MkdirAll(dest,0700));continue};must(os.MkdirAll(filepath.Dir(dest),0700))
  in,e:=entry.Open();must(e);out,e:=os.OpenFile(dest,os.O_WRONLY|os.O_CREATE|os.O_EXCL,0600);must(e);_,e=io.Copy(out,io.LimitReader(in,128*1024*1024));must(e);must(out.Close());in.Close()
 }
 target:=filepath.Join(parent,release.Version);if *extract!=""{target=filepath.Join(parent,"GuildSimBeta-"+release.Version)}
 if _,e=os.Stat(target);os.IsNotExist(e){must(os.Rename(stage,target))}
 // Always validate existing installations before reusing them.
 check:=exec.Command(filepath.Join(target,"GuildSim Helper.exe"),"--diagnose","--report",filepath.Join(root,"install-health.json"));check.Dir=target;hidden(check);must(check.Run())
 if *extract!=""{return}
 launcher:=filepath.Join(root,"GuildSim Launcher.exe");if _,e=os.Stat(launcher);os.IsNotExist(e){data,e:=os.ReadFile(filepath.Join(target,"GuildSim Launcher.exe"));must(e);must(os.WriteFile(launcher,data,0700))}
 activePath:=filepath.Join(root,"active.json");active:=map[string]any{};if b,e:=os.ReadFile(activePath);e==nil{json.Unmarshal(b,&active)}
 old,_:=active["version"].(string);sequence,_:=active["sequence"].(float64)
 if int(sequence)<=release.Sequence {active=map[string]any{"version":release.Version,"previous":old,"sequence":release.Sequence};data,e:=json.Marshal(active);must(e);tmp:=activePath+".new";must(os.WriteFile(tmp,data,0600));must(replace(tmp,activePath))}
 shortcuts(launcher);cmd:=exec.Command(launcher);hidden(cmd);must(cmd.Start())
}
