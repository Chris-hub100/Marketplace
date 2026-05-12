/**
 * LEDGEHOLD PAYOUT SECURITY PROTOCOL
 * Handles IP Recording and Device Fingerprinting for "Instant Handshake"
 */

const SecurityProtocol = {
    
    /**
     * STAGE 1: AT CHECKOUT (Buyer side)
     * Call this when the user clicks "Confirm & Buy"
     */
    async generateSecurityStamp() {
        // 1. Generate unique device token (The "Digital Fingerprint")
        let deviceToken = localStorage.getItem('ledgehold_device_token');
        if (!deviceToken) {
            deviceToken = crypto.randomUUID();
            localStorage.setItem('ledgehold_device_token', deviceToken);
        }

        // 2. Fetch Public IP (Client-side fetch to avoid proxy issues)
        let clientIp = 'unknown';
        try {
            const response = await fetch('https://api.ipify.org?format=json');
            const data = await response.json();
            clientIp = data.ip;
        } catch (e) {
            console.warn("IP Fetch failed, relying on device token.");
        }

        return {
            ip: clientIp,
            token: deviceToken,
            timestamp: Date.now(),
            userAgent: navigator.userAgent
        };
    },

    /**
     * STAGE 2: AT HANDSHAKE (Delivery side)
     * Call this when the QR code is scanned
     */
    async verifyHandshake(originalStamp) {
        const currentStamp = await this.generateSecurityStamp();
        
        // LOGIC: High Confidence Match
        const isIpMatch = currentStamp.ip === originalStamp.ip;
        const isTokenMatch = currentStamp.token === originalStamp.token;

        // If EITHER the IP is the same OR it's the exact same browser/device
        if (isIpMatch || isTokenMatch) {
            return { verified: true, method: isTokenMatch ? 'DEVICE_TOKEN' : 'IP_ADDRESS' };
        } else {
            return { verified: false, reason: 'DEVICE_MISMATCH' };
        }
    }
};

// Export for usage
window.LedgeholdSecurity = SecurityProtocol;