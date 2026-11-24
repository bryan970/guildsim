package trust
import("crypto/ed25519";"encoding/hex";"fmt";"strings")
// PublicKey is filled by the local release build. No private key is embedded.
var PublicKey = "UNCONFIGURED"
func Verify(data []byte,signature string) error {
 pub,err:=hex.DecodeString(PublicKey);if err!=nil||len(pub)!=ed25519.PublicKeySize{return fmt.Errorf("invalid installed release key")}
 sig,err:=hex.DecodeString(strings.TrimSpace(signature));if err!=nil||len(sig)!=ed25519.SignatureSize{return fmt.Errorf("invalid release signature")}
 if !ed25519.Verify(ed25519.PublicKey(pub),data,sig){return fmt.Errorf("release signature did not verify")};return nil
}
