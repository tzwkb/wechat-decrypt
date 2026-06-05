# WeChat 4.0 Windows key extractor (PowerShell + inline C#, no Python needed).
# Reuses wecom find_key.ps1 memory-scan framework; verification = AES-decrypt page1 header.
#
# WeChat 4.0 = standard SQLCipher v4. The AES encryption_key = PBKDF2-HMAC-SHA512(raw, salt, 256000),
# which SQLCipher keeps live in process memory to decrypt pages. Verified locally on macOS: that key
# AES-CBC-decrypts page1[16:32] to "10 00 02 02 50 40 20 20" (page size 4096, reserve 80, fractions).
#
# So: scan Weixin.exe private writable memory for a 32-byte candidate; AES-CBC-decrypt the first
# ciphertext block (page1[16:32]) with IV=page1[4016:4032]; a valid key yields the SQLite header bytes.
# One AES block per candidate -> cheap enough to test every 8-byte-aligned position.
# Keep the inline C# block ASCII-only (Win PowerShell reads files as ANSI/GBK).
$ErrorActionPreference = 'Continue'

$cs = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

public class KeyScan {
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint a, bool inh, int pid);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll", SetLastError=true)] static extern long VirtualQueryEx(IntPtr h, IntPtr addr, out MBI mbi, uint len);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, IntPtr size, out IntPtr read);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr h, uint acc, out IntPtr tok);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool LookupPrivilegeValue(string s, string n, out long luid);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool AdjustTokenPrivileges(IntPtr tok, bool dis, ref TP newp, uint len, IntPtr prev, IntPtr ret);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();

    [StructLayout(LayoutKind.Sequential)] struct MBI {
        public IntPtr BaseAddress, AllocationBase;
        public uint AllocationProtect, __a1;
        public IntPtr RegionSize;
        public uint State, Protect, Type, __a2;
    }
    [StructLayout(LayoutKind.Sequential)] struct TP { public uint Count; public long Luid; public uint Attr; }

    const uint MEM_COMMIT=0x1000, MEM_PRIVATE=0x20000;
    const uint PAGE_RW=0x04, PAGE_WC=0x08, PAGE_GUARD=0x100, PAGE_NOACCESS=0x01;

    static byte[] CT16, IV16;
    static Aes AES;

    public static void EnableDebug() {
        IntPtr tok; if (!OpenProcessToken(GetCurrentProcess(), 0x20|0x08, out tok)) return;
        long luid; if (!LookupPrivilegeValue(null, "SeDebugPrivilege", out luid)) return;
        TP tp = new TP(); tp.Count=1; tp.Luid=luid; tp.Attr=0x2;
        AdjustTokenPrivileges(tok, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero);
    }

    static int PC(ulong x){ int c=0; while(x!=0){ x&=x-1; c++; } return c; }

    // candidate = AES encryption_key; CBC-decrypt page1[16:32], expect SQLite header bytes.
    static bool Verify(byte[] key){
        AES.Key=key;
        using(var d=AES.CreateDecryptor()){
            byte[] dec=d.TransformFinalBlock(CT16,0,16);
            return dec[0]==0x10 && dec[1]==0x00 && dec[4]==0x50 && dec[5]==0x40 && dec[7]==0x20;
        }
    }

    public static List<string> Run(int pid, byte[] page1, int naMin, int distMin, out long mb, out long cand) {
        CT16=new byte[16]; Array.Copy(page1,16,CT16,0,16);
        IV16=new byte[16]; Array.Copy(page1,4016,IV16,0,16);
        AES=Aes.Create(); AES.Mode=CipherMode.CBC; AES.Padding=PaddingMode.None; AES.IV=IV16;
        var found=new List<string>(); mb=0; cand=0;
        IntPtr h=OpenProcess(0x0010|0x0400, false, pid);
        if (h==IntPtr.Zero) throw new Exception("OpenProcess "+pid+" failed err="+Marshal.GetLastWin32Error());
        IntPtr addr=IntPtr.Zero; MBI mbi; uint sz=(uint)Marshal.SizeOf(typeof(MBI));
        long scanned=0;
        while (VirtualQueryEx(h, addr, out mbi, sz)!=0) {
            ulong baseA=(ulong)mbi.BaseAddress.ToInt64();
            ulong size=(ulong)mbi.RegionSize.ToInt64();
            bool ok = mbi.State==MEM_COMMIT
                      && (mbi.Protect==0x02 || mbi.Protect==PAGE_RW || mbi.Protect==PAGE_WC
                          || mbi.Protect==0x20 || mbi.Protect==0x40 || mbi.Protect==0x80)
                      && (mbi.Protect & (PAGE_GUARD|PAGE_NOACCESS))==0;
            if (ok && size>0 && size<0x40000000UL) {
                try {
                    byte[] buf=new byte[size]; IntPtr rd;
                    if (ReadProcessMemory(h, mbi.BaseAddress, buf, (IntPtr)size, out rd)) {
                        int n=(int)rd; scanned+=n;
                        for (int o=0; o+32<=n; o+=8) {
                            int na=0; ulong m0=0,m1=0,m2=0,m3=0;
                            for(int j=0;j<32;j++){
                                byte v=buf[o+j];
                                int w=v>>6; ulong bit=1UL<<(v&63);
                                if(w==0)m0|=bit; else if(w==1)m1|=bit; else if(w==2)m2|=bit; else m3|=bit;
                                if(v<0x20||v>0x7e) na++;
                            }
                            if(na<naMin) continue;
                            if(PC(m0)+PC(m1)+PC(m2)+PC(m3)<distMin) continue;
                            cand++;
                            byte[] ck=new byte[32]; Array.Copy(buf,o,ck,0,32);
                            if(Verify(ck)){
                                found.Add(BitConverter.ToString(ck).Replace("-","").ToLower());
                                CloseHandle(h); mb=scanned/1048576; return found;
                            }
                        }
                    }
                } catch {}
            }
            ulong next=baseA+size; if(next<=baseA) break;
            addr=(IntPtr)(long)next; if(next>0x7FFFFFFFFFFFUL) break;
        }
        CloseHandle(h); mb=scanned/1048576; return found;
    }
}
'@
Add-Type -TypeDefinition $cs -Language CSharp
[KeyScan]::EnableDebug()

# Locate the largest message_0.db across all users (data dir lives under another account).
$mdb = $null
foreach ($ud in (Get-ChildItem "C:\Users" -Directory -ErrorAction SilentlyContinue)) {
    $wx = Join-Path $ud.FullName "Documents\xwechat_files"
    if (-not (Test-Path $wx)) { continue }
    foreach ($f in (Get-ChildItem $wx -Filter message_0.db -Recurse -Depth 4 -ErrorAction SilentlyContinue)) {
        if (-not $mdb -or $f.Length -gt (Get-Item $mdb).Length) { $mdb = $f.FullName }
    }
}
if (-not $mdb) { "NO_MESSAGE_DB"; exit }
"message_0.db: $mdb"
$page1 = New-Object byte[] 4096
$fsr = [System.IO.File]::Open($mdb,"Open","Read","ReadWrite"); [void]$fsr.Read($page1,0,4096); $fsr.Close()

$procs = Get-Process -Name Weixin -ErrorAction SilentlyContinue | Sort-Object WorkingSet64 -Descending
if (-not $procs) { "NO_WEIXIN_PROCESS"; exit }
"Weixin PIDs: " + (($procs | ForEach-Object { "$($_.Id)($([math]::Round($_.WorkingSet64/1MB))MB)" }) -join ' ')

$NA_MIN = 12; $DIST_MIN = 22
foreach ($p in $procs) {
    $mb = 0; $cand = 0
    try { $keys = [KeyScan]::Run($p.Id, $page1, $NA_MIN, $DIST_MIN, [ref]$mb, [ref]$cand) }
    catch { "PID $($p.Id) FAILED: $($_.Exception.Message)"; continue }
    "PID $($p.Id): scanned ${mb}MB, candidates ${cand}, hits $($keys.Count)"
    if ($keys.Count -gt 0) { "FOUND_KEY:"; $keys | ForEach-Object { "KEY=$_" }; exit }
}
"NO_KEY_FOUND (key not found in private RW memory - may live in another region/process)"
