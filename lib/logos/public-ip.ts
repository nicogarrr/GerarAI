/**
 * Validación de IPs públicas, para decidir si un nombre DNS puede
 * resolverse para una petición saliente del servidor (anti-SSRF).
 *
 * Módulo puro y sin dependencias (ni siquiera node:net): lo usan el logo
 * fetcher y sus tests. Una IP es pública solo si es unicast global de verdad:
 * se rechazan loopback, privadas (RFC 1918), link-local, CGNAT, multicast,
 * rangos de documentación/benchmark y las traducciones que incrustan una
 * IPv4 (mapeadas ::ffff:, NAT64 64:ff9b::/96, 6to4 2002::/16, Teredo
 * 2001::/32) — en esas se mira la IPv4 incrustada cuando es legible y, si no
 * lo es, se rechaza (un 6to4/Teredo opaco puede esconder una IP interna).
 */

function parseIPv4(ip: string): number[] | null {
    const m = ip.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
    if (!m) return null;
    const octets = m.slice(1).map(Number);
    return octets.every((n) => n >= 0 && n <= 255) ? octets : null;
}

export function isPublicIPv4(ip: string): boolean {
    const o = parseIPv4(ip);
    if (!o) return false;
    const [a, b, c] = o;
    if (a === 0 || a === 10 || a === 127 || a >= 224) return false; // "esta red", privada, loopback, multicast/reservada
    if (a === 100 && b >= 64 && b <= 127) return false; // CGNAT 100.64.0.0/10
    if (a === 169 && b === 254) return false; // link-local (169.254.169.254: metadata de cloud)
    if (a === 172 && b >= 16 && b <= 31) return false; // privada 172.16.0.0/12
    if (a === 192 && b === 0) return false; // 192.0.0.0/24 (IETF) y 192.0.2.0/24 (TEST-NET-1)
    if (a === 192 && b === 168) return false; // privada
    if (a === 198 && (b === 18 || b === 19)) return false; // benchmark 198.18.0.0/15
    if (a === 198 && b === 51 && c === 100) return false; // TEST-NET-2
    if (a === 203 && b === 0 && c === 113) return false; // TEST-NET-3
    return true;
}

export function isPublicIPv6(ipRaw: string): boolean {
    const ip = ipRaw.toLowerCase();
    if (ip === '::' || ip === '::1') return false; // unspecified y loopback
    // IPv4-mapeada (::ffff:a.b.c.d): se decide por la IPv4 incrustada; la
    // forma hexadecimal comprimida no se puede verificar y se rechaza.
    if (ip.startsWith('::ffff:')) {
        const tail = ip.slice('::ffff:'.length);
        return tail.includes('.') ? isPublicIPv4(tail) : false;
    }
    // NAT64 well-known prefix: igual, la IPv4 incrustada manda.
    if (ip.startsWith('64:ff9b::')) {
        const tail = ip.slice('64:ff9b::'.length);
        return tail.includes('.') ? isPublicIPv4(tail) : false;
    }
    if (/^(fe[89ab]|f[cd]|ff)/.test(ip)) return false; // link-local fe80::/10, ULA fc00::/7, multicast ff00::/8
    if (!/^[23]/.test(ip)) return false; // fuera del unicast global 2000::/3
    if (ip.startsWith('2002:')) return false; // 6to4 (incrusta IPv4, opaca)
    if (ip.startsWith('2001::') || ip.startsWith('2001:0:')) return false; // Teredo 2001:0000::/32
    if (ip.startsWith('2001:db8')) return false; // documentación 2001:db8::/32
    return true;
}

/** `true` solo si la cadena es una IP (v4 o v6) públicamente enrutable. */
export function isPublicIp(ip: string): boolean {
    return ip.includes(':') ? isPublicIPv6(ip) : isPublicIPv4(ip);
}
