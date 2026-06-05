// Frida script to hook CCKeyDerivationPBKDF and capture WeChat DB keys
// Usage: frida -f /Applications/WeChat.app/Contents/MacOS/WeChat -l hook_pbkdf.js
// Compatible with Frida 17.x+ (findGlobalExportByName)

const captured = new Set();

const pbkdf = Module.findGlobalExportByName("CCKeyDerivationPBKDF");
if (!pbkdf) {
    console.log("CCKeyDerivationPBKDF not found! Searching for PBKDF exports...");
    Process.enumerateModules().forEach(m => {
        m.enumerateExports().forEach(e => {
            if (e.name.includes("PBKDF") || e.name.includes("DeriveKey") || e.name.includes("pbkdf")) {
                console.log(`  ${m.name}: ${e.name} @ ${e.address}`);
            }
        });
    });
} else {
    console.log("Found CCKeyDerivationPBKDF at", pbkdf);

    Interceptor.attach(pbkdf, {
        onEnter(args) {
            // CCKeyDerivationPBKDF(algorithm, password, passwordLen, salt, saltLen, prf, rounds, derivedKey, derivedKeyLen)
            const algorithm = args[0].toInt32();
            const password = args[1];
            const passwordLen = args[2].toInt32();
            const salt = args[3];
            const saltLen = args[4].toInt32();
            const prf = args[5].toInt32();
            const rounds = args[6].toInt32();
            const derivedKey = args[7];
            const derivedKeyLen = args[8] ? args[8].toInt32() : 0;

            this.dkPtr = derivedKey;
            this.dkLen = derivedKeyLen;

            // Only capture WeChat's key derivation: dkLen=32 (AES-256), rounds>1000 (PBKDF2), passwordLen=32 (raw key)
            if (derivedKeyLen === 32 && rounds > 1000 && passwordLen === 32) {
                try {
                    const rawKeyBytes = password.readByteArray(passwordLen);
                    const rawKeyHex = Array.from(new Uint8Array(rawKeyBytes))
                        .map(b => b.toString(16).padStart(2, '0')).join('');
                    if (!captured.has(rawKeyHex)) {
                        captured.add(rawKeyHex);
                        console.log(`RAW_KEY=${rawKeyHex}`);
                    }
                } catch(e) {
                    console.log(`[PBKDF2] rounds=${rounds} saltLen=${saltLen} dkLen=${derivedKeyLen} (params unavailable: ${e})`);
                }
                this.shouldCapture = true;
            } else {
                this.shouldCapture = false;
            }
        },

        onLeave(retval) {
            if (this.shouldCapture && retval.toInt32() === 0) {
                try {
                    const key = this.dkPtr.readByteArray(this.dkLen);
                    const keyHex = Array.from(new Uint8Array(key))
                        .map(b => b.toString(16).padStart(2, '0')).join('');
                    if (!captured.has(keyHex)) {
                        captured.add(keyHex);
                        console.log(`DERIVED_KEY=${keyHex}`);
                    }
                } catch(e) {
                    console.log(`Failed to read derived key: ${e}`);
                }
            }
        }
    });
}

console.log("Frida hooks installed. Waiting for PBKDF2 calls...");
