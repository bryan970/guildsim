// Build-machine utility. This executable and private key are never distributed.
package main
import("crypto/ed25519";"crypto/rand";"encoding/hex";"flag";"fmt";"os")
func main(){key:=flag.String("key","","private key file");init:=flag.Bool("init",false,"create key");file:=flag.String("file","","manifest");out:=flag.String("out","","signature");flag.Parse()
 if *init {pub,priv,e:=ed25519.GenerateKey(rand.Reader);if e!=nil{panic(e)};if e=os.WriteFile(*key,priv,0600);e!=nil{panic(e)};fmt.Println(hex.EncodeToString(pub));return}
 priv,e:=os.ReadFile(*key);if e!=nil{panic(e)};if len(priv)!=ed25519.PrivateKeySize{panic("invalid signing key")};data,e:=os.ReadFile(*file);if e!=nil{panic(e)};sig:=ed25519.Sign(ed25519.PrivateKey(priv),data);if e=os.WriteFile(*out,[]byte(hex.EncodeToString(sig)),0644);e!=nil{panic(e)}
}
