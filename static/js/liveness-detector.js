/**
 * Ledgehold Liveness Detection Module
 * Uses face-api.js for real-time face detection with challenge-response verification.
 * Works on desktop (webcam) and mobile (front camera).
 *
 * REQUIRES face-api.js loaded BEFORE this script:
 *   <script defer src="https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js"></script>
 *
 * face-api.js model weights must be hosted at MODEL_URL below (or overridden via options).
 * Minimum required model files (place in /models/):
 *   tiny_face_detector_model-weights_manifest.json + shard file
 *   face_landmark_68_model-weights_manifest.json   + shard file
 */

class LivenessDetector {
    constructor(options = {}) {
        this.video         = null;
        this.stream        = null;
        this.canvas        = null;
        this.modelUrl      = options.modelUrl || '/models';  // <-- set your model path here

        this.challenges           = ['blink', 'turnLeft', 'turnRight', 'smile'];
        this.currentChallenge     = null;
        this.completedChallenges  = 0;
        this.requiredChallenges   = options.requiredChallenges || 2;
        this.challengeActive      = false;
        this.challengeTimeout     = null;
        this.noFaceTimeout        = null;   // fires if no face seen at challenge start
        this.running              = false;  // guards the RAF loop

        this.onComplete  = options.onComplete  || (() => {});
        this.onFail      = options.onFail      || (() => {});
        this.onProgress  = options.onProgress  || (() => {});
        this.capturedImage = null;

        // Per-challenge detection state (reset in pickNextChallenge)
        this.faceHistory      = [];
        this.eyesWereClosed   = false;
        this.blinkCount       = 0;
        this.faceSeenInChallenge = false;  // true once ≥1 detection fires this challenge

        // ── Capture-phase state ─────────────────────────────────────────────
        // After all challenges pass we enter a "get ready" countdown before
        // the still-frame is captured.  The countdown only advances while the
        // user is facing the camera and not moving.
        this._capturePhase        = false;  // true once challenges are all done
        this._captureCountdown    = 3;      // seconds remaining
        this._captureLastTick     = null;   // timestamp of last successful tick
        this._captureTickTimer    = null;   // setInterval handle
        this._captureFaceOk       = false;  // set by detection loop each frame
        this._captureStillHistory = [];     // nose positions for stillness check

        // Bind loop so we can cancel it cleanly
        this._loopBound = this._detectionLoop.bind(this);
    }

    // ─────────────────────────────────────────────────────────────────────────
    // PUBLIC API
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Start the liveness detection flow.
     * @param {HTMLElement} videoContainer - DOM element to mount the video preview
     */
    async start(videoContainer) {
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: 'user',
                    width:  { ideal: 640 },
                    height: { ideal: 480 }
                }
            });
        } catch (err) {
            console.error('Liveness camera error:', err);
            this.onFail('Camera access denied. Please allow camera permissions and try again.');
            return;
        }

        // ── Video element ──────────────────────────────────────────────────
        this.video = document.createElement('video');
        this.video.srcObject = this.stream;
        this.video.setAttribute('playsinline', '');
        this.video.setAttribute('autoplay', '');
        this.video.muted = true;
        this.video.style.cssText = [
            'width:100%',
            'display:block',
            'border-radius:12px',
            'transform:scaleX(-1)'   // mirror for selfie UX
        ].join(';');
        videoContainer.appendChild(this.video);

        try {
            await this.video.play();
        } catch (err) {
            this.stop();
            this.onFail('Could not start camera preview. Please try again.');
            return;
        }

        // ── Overlay canvas ─────────────────────────────────────────────────
        this.canvas = document.createElement('canvas');
        this.canvas.style.cssText = [
            'position:absolute',
            'top:0',
            'left:0',
            'width:100%',
            'height:100%',
            'pointer-events:none',
            'transform:scaleX(-1)'   // mirror to match video
        ].join(';');
        videoContainer.style.position = 'relative';
        videoContainer.appendChild(this.canvas);

        // ── Load models ────────────────────────────────────────────────────
        try {
            await this._loadModels();
        } catch (modelErr) {
            this.stop();
            this.onFail(modelErr.message);
            return;
        }

        // ── Start loop & first challenge ───────────────────────────────────
        this.running = true;
        requestAnimationFrame(this._loopBound);
        setTimeout(() => this.pickNextChallenge(), 1500);
    }

    stop() {
        this.running = false;
        this.challengeActive = false;
        this._capturePhase = false;
        clearTimeout(this.challengeTimeout);
        clearTimeout(this.noFaceTimeout);
        clearInterval(this._captureTickTimer);

        if (this.stream) {
            this.stream.getTracks().forEach(t => t.stop());
            this.stream = null;
        }
        if (this.video)  { this.video.remove();  this.video  = null; }
        if (this.canvas) { this.canvas.remove(); this.canvas = null; }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MODEL LOADING
    // ─────────────────────────────────────────────────────────────────────────

    async _loadModels() {
        // Wait until face-api.js itself is available (it may still be parsing)
        await this._waitFor(() => !!window.faceapi, 15000,
            'face-api.js library did not load. Please refresh and try again.');

        // Load model weights if not already loaded
        const nets = faceapi.nets;

        if (!nets.tinyFaceDetector.isLoaded) {
            await nets.tinyFaceDetector.loadFromUri(this.modelUrl);
        }
        if (!nets.faceLandmark68TinyNet) {
            // prefer the tiny landmark net for performance
        }
        // Use full landmark net — tiny net is not always bundled
        if (!nets.faceLandmark68Net.isLoaded) {
            await nets.faceLandmark68Net.loadFromUri(this.modelUrl);
        }

        console.log('✅ face-api models loaded');
    }

    /** Poll `predicate` every 200 ms up to `timeoutMs`. Rejects with `msg` on timeout. */
    _waitFor(predicate, timeoutMs = 10000, msg = 'Timeout') {
        return new Promise((resolve, reject) => {
            const interval = 200;
            let elapsed = 0;
            const id = setInterval(() => {
                if (predicate()) { clearInterval(id); resolve(); return; }
                elapsed += interval;
                if (elapsed >= timeoutMs) { clearInterval(id); reject(new Error(msg)); }
            }, interval);
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // DETECTION LOOP
    // ─────────────────────────────────────────────────────────────────────────

    async _detectionLoop() {
        if (!this.running) return;

        // Don't run if video is not yet playing
        if (this.video && this.video.readyState === 4) {
            try {
                const detection = await faceapi
                    .detectSingleFace(this.video, new faceapi.TinyFaceDetectorOptions({ scoreThreshold: 0.4 }))
                    .withFaceLandmarks();   // uses full 68-point net by default

                this._drawOverlay(detection);

                if (detection) {
                    // ── Face is visible ────────────────────────────────────
                    if (this.challengeActive && !this.faceSeenInChallenge) {
                        // First detection this challenge — cancel the no-face timeout
                        this.faceSeenInChallenge = true;
                        clearTimeout(this.noFaceTimeout);
                        this.noFaceTimeout = null;
                    }

                    // Track nose tip (point 30) as a stable face-centre proxy
                    const nose = detection.landmarks.getNose()[3]; // base of nose
                    this.faceHistory.push({ x: nose.x, y: nose.y, time: Date.now() });

                    // Keep only the last 2 s of history
                    const now = Date.now();
                    this.faceHistory = this.faceHistory.filter(h => now - h.time < 2000);

                    if (this.challengeActive) {
                        this._evaluateChallenge(detection);
                    }

                    // ── Feed capture-phase stillness checker ───────────────
                    if (this._capturePhase) {
                        this._captureFaceOk = this._isFaceReadyForCapture(detection);
                    }
                } else {
                    // ── No face in frame ───────────────────────────────────
                    this.faceHistory = [];

                    if (this._capturePhase) {
                        // Face lost during countdown — signal the tick handler
                        this._captureFaceOk = false;
                    }
                }
            } catch (err) {
                // Swallow per-frame errors (e.g. video frame not ready yet)
            }
        }

        if (this.running) {
            requestAnimationFrame(this._loopBound);
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // CANVAS OVERLAY
    // ─────────────────────────────────────────────────────────────────────────

    _drawOverlay(detection) {
        if (!this.canvas || !this.video) return;

        // Sync canvas resolution to actual video stream resolution (once)
        if (
            this.canvas.width  !== this.video.videoWidth ||
            this.canvas.height !== this.video.videoHeight
        ) {
            this.canvas.width  = this.video.videoWidth  || 640;
            this.canvas.height = this.video.videoHeight || 480;
        }

        const ctx = this.canvas.getContext('2d');
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        if (!detection) return;

        const box = detection.detection.box;
        const cx  = box.x + box.width  / 2;
        const cy  = box.y + box.height / 2;
        const rx  = box.width  / 2 + 14;
        const ry  = box.height / 2 + 14;

        // Oval colour: green during challenges / yellow-amber during capture phase
        const strokeColor = this._capturePhase
            ? (this._captureFaceOk ? '#f59e0b' : '#ef4444')
            : '#10b981';

        ctx.save();
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth   = 3;
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.ellipse(cx, cy, rx, ry, 0, 0, 2 * Math.PI);
        ctx.stroke();
        ctx.restore();

        // Draw countdown number centred in the oval during capture phase
        if (this._capturePhase && this._captureFaceOk) {
            ctx.save();
            ctx.fillStyle    = '#f59e0b';
            ctx.font         = `bold ${Math.round(ry * 0.9)}px sans-serif`;
            ctx.textAlign    = 'center';
            ctx.textBaseline = 'middle';
            ctx.globalAlpha  = 0.85;
            // Counter-mirror the text: translate to the draw point, flip X, draw at origin
            ctx.translate(cx, cy);
            ctx.scale(-1, 1);
            ctx.fillText(String(this._captureCountdown), 0, 0);
            ctx.restore();
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // CHALLENGE MANAGEMENT
    // ─────────────────────────────────────────────────────────────────────────

    pickNextChallenge() {
        if (this.completedChallenges >= this.requiredChallenges) {
            this._startCaptureCountdown();
            return;
        }

        // Pick a challenge different from the previous one
        const available = this.challenges.filter(c => c !== this.currentChallenge);
        this.currentChallenge    = available[Math.floor(Math.random() * available.length)];
        this.challengeActive     = true;
        this.faceSeenInChallenge = false;

        // Reset per-challenge state
        this.faceHistory    = [];
        this.eyesWereClosed = false;
        this.blinkCount     = 0;

        const instructions = {
            blink:     'Blink your eyes twice',
            turnLeft:  'Slowly turn your head to the left',
            turnRight: 'Slowly turn your head to the right',
            smile:     'Give a big smile'
        };

        this.onProgress({
            challenge:   this.currentChallenge,
            instruction: instructions[this.currentChallenge],
            completed:   this.completedChallenges,
            total:       this.requiredChallenges
        });

        // ── No-face grace period (3 s) ─────────────────────────────────────
        clearTimeout(this.noFaceTimeout);
        this.noFaceTimeout = setTimeout(() => {
            if (!this.challengeActive) return;
            if (!this.faceSeenInChallenge) {
                this.challengeActive = false;
                clearTimeout(this.challengeTimeout);
                this.stop();
                this.onFail('No face detected. Please position your face in the frame and try again.');
            }
        }, 3000);

        // ── Challenge completion timeout (8 s) ─────────────────────────────
        clearTimeout(this.challengeTimeout);
        this.challengeTimeout = setTimeout(() => {
            if (!this.challengeActive) return;

            if (!this.faceSeenInChallenge) {
                this.challengeActive = false;
                clearTimeout(this.noFaceTimeout);
                this.stop();
                this.onFail('No face detected. Please position your face in the frame and try again.');
                return;
            }

            // Face was seen but gesture wasn't completed — prompt a retry
            this.challengeActive = false;
            clearTimeout(this.noFaceTimeout);

            this.onProgress({
                challenge:   this.currentChallenge,
                instruction: "Couldn't detect that gesture, let's try again",
                completed:   this.completedChallenges,
                total:       this.requiredChallenges
            });

            setTimeout(() => {
                if (this.running) this.pickNextChallenge();
            }, 1200);
        }, 8000);
    }

    _completeChallenge() {
        if (!this.challengeActive) return;  // guard against double-fire
        this.challengeActive = false;
        clearTimeout(this.challengeTimeout);
        clearTimeout(this.noFaceTimeout);
        this.completedChallenges++;

        this.onProgress({
            challenge:   this.currentChallenge,
            instruction: '✓ Done!',
            completed:   this.completedChallenges,
            total:       this.requiredChallenges
        });

        setTimeout(() => this.pickNextChallenge(), 800);
    }

    // ─────────────────────────────────────────────────────────────────────────
    // CAPTURE-PHASE: STILLNESS COUNTDOWN
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Called once all required challenges are completed.
     * Asks the user to hold still and face the camera.
     * Counts down 3 → 2 → 1 (only while the face is centred and still),
     * then fires _finalize().  The countdown is paused/reset any time the
     * user moves too much or looks away.
     */
    _startCaptureCountdown() {
        this._capturePhase        = true;
        this._captureCountdown    = 3;
        this._captureFaceOk       = false;
        this._captureStillHistory = [];

        // Brief pause before the countdown UI appears so the "✓ Done!" message
        // is readable.
        setTimeout(() => {
            if (!this.running || !this._capturePhase) return;

            this.onProgress({
                challenge:   'capture',
                instruction: 'Hold still and face the camera…',
                completed:   this.completedChallenges,
                total:       this.requiredChallenges,
                countdown:   this._captureCountdown
            });

            // Tick every second — only advance when the face is ready
            this._captureTickTimer = setInterval(() => {
                if (!this.running || !this._capturePhase) {
                    clearInterval(this._captureTickTimer);
                    return;
                }

                if (!this._captureFaceOk) {
                    // Face not ready — reset the counter and re-prompt
                    this._captureCountdown = 3;
                    this.onProgress({
                        challenge:   'capture',
                        instruction: 'Hold still and face the camera…',
                        completed:   this.completedChallenges,
                        total:       this.requiredChallenges,
                        countdown:   this._captureCountdown
                    });
                    return;
                }

                // Face is ready — advance the countdown
                this._captureCountdown--;

                if (this._captureCountdown <= 0) {
                    clearInterval(this._captureTickTimer);
                    this._finalize();
                } else {
                    this.onProgress({
                        challenge:   'capture',
                        instruction: `Hold still… ${this._captureCountdown}`,
                        completed:   this.completedChallenges,
                        total:       this.requiredChallenges,
                        countdown:   this._captureCountdown
                    });
                }
            }, 1000);
        }, 600);
    }

    /**
     * Returns true when the face is centred in frame, frontal, and not moving.
     * Called every animation frame during the capture phase.
     *
     * Criteria
     * ────────
     * 1. Face is detected (detection is truthy — caller guarantees this).
     * 2. Face bounding box is reasonably centred (within the middle 60 % of
     *    the frame width and within the middle 70 % of the frame height).
     * 3. Head is roughly frontal: the nose is close to the horizontal
     *    midpoint of the eyes (yaw check, ±15 % of face width).
     * 4. Face is still: nose position has moved less than 12 px (raw video
     *    coords) over the last 800 ms of tracked history.
     */
    _isFaceReadyForCapture(detection) {
        const vw = this.video.videoWidth  || 640;
        const vh = this.video.videoHeight || 480;

        // ── 1. Centring check ──────────────────────────────────────────────
        const box = detection.detection.box;
        const faceCx = box.x + box.width  / 2;
        const faceCy = box.y + box.height / 2;

        const marginX = vw * 0.20;  // face centre must be in middle 60 % of width
        const marginY = vh * 0.15;  // face centre must be in middle 70 % of height

        if (
            faceCx < marginX || faceCx > vw - marginX ||
            faceCy < marginY || faceCy > vh - marginY
        ) {
            return false;
        }

        // ── 2. Frontality check (yaw) ──────────────────────────────────────
        // Compare the horizontal midpoint of the two eye centres with the
        // nose base.  If the difference is more than 15 % of face width the
        // user is turned too far.
        const leftEye  = detection.landmarks.getLeftEye();
        const rightEye = detection.landmarks.getRightEye();
        const nose     = detection.landmarks.getNose();

        const leftEyeCx  = leftEye.reduce((s, p) => s + p.x, 0)  / leftEye.length;
        const rightEyeCx = rightEye.reduce((s, p) => s + p.x, 0) / rightEye.length;
        const eyeMidX    = (leftEyeCx + rightEyeCx) / 2;
        const noseTipX   = nose[3].x;  // base of nose

        const yawOffset  = Math.abs(noseTipX - eyeMidX);
        const faceWidth  = box.width;

        if (yawOffset > faceWidth * 0.15) {
            return false;
        }

        // ── 3. Stillness check ─────────────────────────────────────────────
        const nosePos = { x: nose[3].x, y: nose[3].y, time: Date.now() };
        this._captureStillHistory.push(nosePos);

        // Keep only the last 800 ms
        const cutoff = Date.now() - 800;
        this._captureStillHistory = this._captureStillHistory.filter(p => p.time >= cutoff);

        if (this._captureStillHistory.length < 3) {
            // Not enough history yet — don't count as ready but don't penalise
            return false;
        }

        // Max displacement across all tracked points
        let maxDist = 0;
        for (const p of this._captureStillHistory) {
            const dist = Math.hypot(p.x - nosePos.x, p.y - nosePos.y);
            if (dist > maxDist) maxDist = dist;
        }

        const STILL_THRESHOLD = 12; // pixels in raw video coords
        return maxDist < STILL_THRESHOLD;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // CHALLENGE EVALUATORS
    // ─────────────────────────────────────────────────────────────────────────

    _evaluateChallenge(detection) {
        switch (this.currentChallenge) {
            case 'blink':     this._evalBlink(detection);           break;
            case 'turnLeft':  this._evalHeadTurn(detection, 'left'); break;
            case 'turnRight': this._evalHeadTurn(detection, 'right');break;
            case 'smile':     this._evalSmile(detection);            break;
        }
    }

    _evalBlink(detection) {
        const leftEye  = detection.landmarks.getLeftEye();
        const rightEye = detection.landmarks.getRightEye();

        const leftOpen  = this._eyeOpenness(leftEye);
        const rightOpen = this._eyeOpenness(rightEye);
        const avgOpen   = (leftOpen + rightOpen) / 2;

        const CLOSED_THRESHOLD = 0.15;
        const OPEN_THRESHOLD   = 0.22;

        if (avgOpen < CLOSED_THRESHOLD && !this.eyesWereClosed) {
            this.eyesWereClosed = true;
        } else if (avgOpen > OPEN_THRESHOLD && this.eyesWereClosed) {
            this.eyesWereClosed = false;
            this.blinkCount++;
            if (this.blinkCount >= 2) {
                this._completeChallenge();
            }
        }
    }

    /**
     * Eye aspect ratio (EAR):
     *   EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)
     * face-api.js returns 6 points per eye: [0]=left corner … [3]=right corner,
     * [1][2] = upper lids, [4][5] = lower lids (68-point model indices within eye set).
     */
    _eyeOpenness(pts) {
        if (!pts || pts.length < 6) return 0.3; // assume open if data missing
        const h = (
            Math.abs(pts[1].y - pts[5].y) +
            Math.abs(pts[2].y - pts[4].y)
        );
        const w = Math.abs(pts[0].x - pts[3].x);
        return w > 1 ? h / (2 * w) : 0;
    }

    _evalHeadTurn(detection, direction) {
        if (this.faceHistory.length < 8) return;

        // Use the earliest vs. latest nose position over the last 2 s
        const first = this.faceHistory[0];
        const last  = this.faceHistory[this.faceHistory.length - 1];

        // The video is mirrored (scaleX(-1)), so left/right in pixel-space
        // is flipped vs. the user's anatomical left/right.
        // face-api detects in raw video coords → apply mirror correction:
        //   pixel deltaX > 0  means the face moved rightward in raw coords
        //                     which appears as leftward movement to the viewer.
        const deltaX   = last.x - first.x;
        const THRESHOLD = 28; // pixels of movement in raw video coords

        if (direction === 'left'  && deltaX > THRESHOLD) {
            this._completeChallenge();
        } else if (direction === 'right' && deltaX < -THRESHOLD) {
            this._completeChallenge();
        }
    }

    _evalSmile(detection) {
        const mouth = detection.landmarks.getMouth();
        // mouth has 20 points in face-api's 68-pt model subset:
        //   outer lip: pts 0-11, inner lip: pts 12-19
        // Width  = distance between pts 0 (left) and 6 (right)
        // Height = distance between pts 3 (top centre) and 9 (bottom centre)
        if (!mouth || mouth.length < 20) return;

        const mouthWidth  = Math.abs(mouth[6].x - mouth[0].x);
        const mouthHeight = Math.abs(mouth[9].y - mouth[3].y);

        if (mouthWidth < 1) return;
        const ratio = mouthHeight / mouthWidth;

        // A natural smile opens the mouth: ratio > 0.20 is reliably a smile.
        // Resting face is typically < 0.10.
        if (ratio > 0.20) {
            this._completeChallenge();
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FINALISATION
    // ─────────────────────────────────────────────────────────────────────────

    _finalize() {
        // Capture a non-mirrored still frame
        const captureCanvas = document.createElement('canvas');
        captureCanvas.width  = this.video.videoWidth  || 640;
        captureCanvas.height = this.video.videoHeight || 480;
        const ctx = captureCanvas.getContext('2d');
        // Draw normally (no mirror) — this.video already carries the stream
        ctx.drawImage(this.video, 0, 0);
        this.capturedImage = captureCanvas.toDataURL('image/jpeg', 0.85);

        this.stop();
        this.onComplete(this.capturedImage);
    }
}

// Expose globally so other scripts can instantiate it
window.LivenessDetector = LivenessDetector;