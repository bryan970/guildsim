package main
import("syscall";"unsafe")
func replace(from,to string)error{a,e:=syscall.UTF16PtrFromString(from);if e!=nil{return e};b,e:=syscall.UTF16PtrFromString(to);if e!=nil{return e};ok,_,err:=syscall.NewLazyDLL("kernel32.dll").NewProc("MoveFileExW").Call(uintptr(unsafe.Pointer(a)),uintptr(unsafe.Pointer(b)),9);if ok==0{return err};return nil}
