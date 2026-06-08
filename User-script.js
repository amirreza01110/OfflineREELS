// ==UserScript==
// @name         Instagram Reels Link Scraper (Popup Config + Dark Theme)
// @namespace    http://tampermonkey.net/
// @version      1.3
// @description  Scrolls Instagram Reels, extracts video links, and saves them in batches with popup settings.
// @author       YourName
// @match        https://www.instagram.com/reels/*
// @match        https://www.instagram.com/reels/
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    // --- Runtime Configuration ---
    let TOTAL_TARGET = 50;
    let BATCH_SIZE = 10;
    let SCROLL_INTERVAL = 4500;
    // -----------------------------

    let collectedLinks = new Set();
    let currentBatch = [];
    let fileCounter = 0;
    let scrollTimer = null;
    let isRunning = false;

    // Trigger the file download
    function downloadBatch(links, index) {
        if (!links.length) return;

        const textContent = links.join('\n');
        const blob = new Blob([textContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = `${index}-Insta-post.txt`;
        document.body.appendChild(a);
        a.click();

        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        console.log(`Saved: ${a.download}`);
    }

    // Validation to filter out audio, profiles, and hashes
    function isValidReelUrl(url) {
        try {
            const parsed = new URL(url);
            const path = parsed.pathname;

            if (path.includes('/audio/') || path.endsWith('/reels/') || path === '/reels' || path === '/reels/') {
                return false;
            }

            const pattern = /^\/(reel|reels)\/[a-zA-Z0-9_\-]+\/?$/;
            return pattern.test(path);
        } catch (e) {
            return false;
        }
    }

    // Robust scroll: Finds the next video container and scrolls to it
    function scrollToNextReel() {
        const activeVideo = document.querySelector('video');
        if (!activeVideo) {
            dispatchArrowDown(document.activeElement || document);
            return;
        }

        const currentCard = activeVideo.closest('article') || activeVideo.closest('[role="presentation"]');
        if (currentCard) {
            const cards = Array.from(document.querySelectorAll('article, [role="presentation"]'));
            const currentIndex = cards.indexOf(currentCard);

            if (currentIndex !== -1 && currentIndex + 1 < cards.length) {
                cards[currentIndex + 1].scrollIntoView({ behavior: 'smooth', block: 'start' });
                return;
            }
        }

        dispatchArrowDown(activeVideo.parentElement || document);
    }

    // Helper to dispatch keypress to a specific element
    function dispatchArrowDown(target) {
        const eventOptions = {
            key: 'ArrowDown',
            keyCode: 40,
            code: 'ArrowDown',
            which: 40,
            bubbles: true,
            cancelable: true,
            view: window
        };
        target.dispatchEvent(new KeyboardEvent('keydown', eventOptions));
        target.dispatchEvent(new KeyboardEvent('keyup', eventOptions));
    }

    function stopScraper(autoSave = true) {
        isRunning = false;
        clearInterval(scrollTimer);
        scrollTimer = null;

        const startBtn = document.getElementById('instaScraperStartBtn');
        const stopBtn = document.getElementById('instaScraperStopBtn');
        const statusText = document.getElementById('instaScraperStatus');

        if (startBtn) startBtn.disabled = false;
        if (stopBtn) stopBtn.disabled = true;
        if (statusText) {
            statusText.textContent = `Stopped | Collected: ${collectedLinks.size}/${TOTAL_TARGET}`;
        }

        console.log('Scraper stopped.');

        if (autoSave && currentBatch.length > 0) {
            downloadBatch(currentBatch, fileCounter);
            fileCounter++;
            currentBatch = [];
        }
    }

    // Main collection logic
    function scanAndScroll() {
        if (!isRunning) return;

        const anchors = document.querySelectorAll('a');

        anchors.forEach(anchor => {
            if (!isRunning) return;
            if (collectedLinks.size >= TOTAL_TARGET) return;

            const href = anchor.href;
            if (!href) return;

            const cleanUrl = href.split('?')[0].split('#')[0];

            if (isValidReelUrl(cleanUrl) && !collectedLinks.has(cleanUrl)) {
                collectedLinks.add(cleanUrl);
                currentBatch.push(cleanUrl);

                console.log(`Added: ${cleanUrl} (${collectedLinks.size}/${TOTAL_TARGET})`);

                const statusText = document.getElementById('instaScraperStatus');
                if (statusText) {
                    statusText.textContent = `Running | Collected: ${collectedLinks.size}/${TOTAL_TARGET}`;
                }

                if (currentBatch.length >= BATCH_SIZE) {
                    downloadBatch(currentBatch, fileCounter);
                    fileCounter++;
                    currentBatch = [];
                }

                if (collectedLinks.size >= TOTAL_TARGET) {
                    console.log('Target reached. Stopping scraper.');
                    stopScraper(true);
                    return;
                }
            }
        });

        if (isRunning && collectedLinks.size < TOTAL_TARGET) {
            scrollToNextReel();
        }
    }

    function showConfigModal(onStart) {
        const overlay = document.createElement('div');
        overlay.id = 'instaScraperOverlay';
        overlay.style.position = 'fixed';
        overlay.style.inset = '0';
        overlay.style.background = 'rgba(0,0,0,0.72)';
        overlay.style.backdropFilter = 'blur(6px)';
        overlay.style.zIndex = '100000';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';

        const modal = document.createElement('div');
        modal.style.width = '380px';
        modal.style.maxWidth = '92vw';
        modal.style.background = 'linear-gradient(145deg, #111827, #0b1220)';
        modal.style.border = '1px solid rgba(255,255,255,0.08)';
        modal.style.borderRadius = '18px';
        modal.style.padding = '22px';
        modal.style.boxShadow = '0 20px 60px rgba(0,0,0,0.55)';
        modal.style.color = '#fff';
        modal.style.fontFamily = 'Inter, Arial, sans-serif';

        modal.innerHTML = `
            <div style="font-size:20px;font-weight:700;margin-bottom:6px;letter-spacing:0.3px;">
                Instagram Reels Scraper
            </div>
            <div style="font-size:13px;color:#9ca3af;margin-bottom:18px;">
                Configure how many reel links you want to collect.
            </div>

            <label style="display:block;font-size:13px;margin-bottom:6px;color:#d1d5db;">
                Total videos to download
            </label>
            <input id="instaTotalVideos" type="number" min="1" value="${TOTAL_TARGET}" style="
                width:100%;
                box-sizing:border-box;
                margin-bottom:14px;
                padding:12px 14px;
                border-radius:12px;
                border:1px solid #2d3748;
                background:#0f172a;
                color:#fff;
                outline:none;
                font-size:14px;
            ">

            <label style="display:block;font-size:13px;margin-bottom:6px;color:#d1d5db;">
                Videos per file
            </label>
            <input id="instaBatchSize" type="number" min="1" value="${BATCH_SIZE}" style="
                width:100%;
                box-sizing:border-box;
                margin-bottom:14px;
                padding:12px 14px;
                border-radius:12px;
                border:1px solid #2d3748;
                background:#0f172a;
                color:#fff;
                outline:none;
                font-size:14px;
            ">

            <label style="display:block;font-size:13px;margin-bottom:6px;color:#d1d5db;">
                Wait between each scroll (ms)
            </label>
            <input id="instaScrollWait" type="number" min="500" value="${SCROLL_INTERVAL}" style="
                width:100%;
                box-sizing:border-box;
                margin-bottom:18px;
                padding:12px 14px;
                border-radius:12px;
                border:1px solid #2d3748;
                background:#0f172a;
                color:#fff;
                outline:none;
                font-size:14px;
            ">

            <div style="display:flex;gap:10px;justify-content:flex-end;">
                <button id="instaCancelConfig" style="
                    padding:10px 16px;
                    border:none;
                    border-radius:12px;
                    cursor:pointer;
                    background:#1f2937;
                    color:#e5e7eb;
                    font-weight:600;
                ">Cancel</button>

                <button id="instaConfirmConfig" style="
                    padding:10px 16px;
                    border:none;
                    border-radius:12px;
                    cursor:pointer;
                    background:linear-gradient(135deg, #7c3aed, #2563eb);
                    color:white;
                    font-weight:700;
                    box-shadow:0 8px 20px rgba(37,99,235,0.35);
                ">Start Scraping</button>
            </div>
        `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        const totalInput = modal.querySelector('#instaTotalVideos');
        const batchInput = modal.querySelector('#instaBatchSize');
        const waitInput = modal.querySelector('#instaScrollWait');
        const cancelBtn = modal.querySelector('#instaCancelConfig');
        const confirmBtn = modal.querySelector('#instaConfirmConfig');

        cancelBtn.addEventListener('click', () => {
            document.body.removeChild(overlay);
        });

        confirmBtn.addEventListener('click', () => {
            const total = parseInt(totalInput.value, 10);
            const batch = parseInt(batchInput.value, 10);
            const wait = parseInt(waitInput.value, 10);

            if (!total || total < 1) {
                alert('Please enter a valid total number of videos.');
                return;
            }
            if (!batch || batch < 1) {
                alert('Please enter a valid number of videos per file.');
                return;
            }
            if (!wait || wait < 500) {
                alert('Please enter a valid wait time (minimum 500 ms).');
                return;
            }

            TOTAL_TARGET = total;
            BATCH_SIZE = batch;
            SCROLL_INTERVAL = wait;

            document.body.removeChild(overlay);
            onStart();
        });
    }

    // UI Control Panel
    function createControlPanel() {
        const panel = document.createElement('div');
        panel.style.position = 'fixed';
        panel.style.bottom = '20px';
        panel.style.right = '20px';
        panel.style.zIndex = '99999';
        panel.style.padding = '14px';
        panel.style.background = 'linear-gradient(145deg, #111827, #0b1220)';
        panel.style.color = '#fff';
        panel.style.border = '1px solid rgba(255,255,255,0.08)';
        panel.style.borderRadius = '16px';
        panel.style.fontFamily = 'Inter, Arial, sans-serif';
        panel.style.boxShadow = '0 12px 35px rgba(0,0,0,0.45)';
        panel.style.minWidth = '240px';

        const title = document.createElement('div');
        title.textContent = 'Reels Scraper';
        title.style.fontSize = '15px';
        title.style.fontWeight = '700';
        title.style.marginBottom = '10px';
        title.style.color = '#f9fafb';

        const statusText = document.createElement('div');
        statusText.id = 'instaScraperStatus';
        statusText.textContent = 'Idle';
        statusText.style.fontSize = '12px';
        statusText.style.color = '#9ca3af';
        statusText.style.marginBottom = '12px';

        const buttonWrap = document.createElement('div');
        buttonWrap.style.display = 'flex';
        buttonWrap.style.gap = '10px';

        const startBtn = document.createElement('button');
        startBtn.id = 'instaScraperStartBtn';
        startBtn.textContent = 'Start';
        startBtn.style.flex = '1';
        startBtn.style.padding = '10px 14px';
        startBtn.style.cursor = 'pointer';
        startBtn.style.border = 'none';
        startBtn.style.borderRadius = '12px';
        startBtn.style.background = 'linear-gradient(135deg, #7c3aed, #2563eb)';
        startBtn.style.color = '#fff';
        startBtn.style.fontWeight = '700';
        startBtn.style.boxShadow = '0 8px 20px rgba(37,99,235,0.35)';

        const stopBtn = document.createElement('button');
        stopBtn.id = 'instaScraperStopBtn';
        stopBtn.textContent = 'Stop';
        stopBtn.style.flex = '1';
        stopBtn.style.padding = '10px 14px';
        stopBtn.style.cursor = 'pointer';
        stopBtn.style.border = 'none';
        stopBtn.style.borderRadius = '12px';
        stopBtn.style.background = '#1f2937';
        stopBtn.style.color = '#e5e7eb';
        stopBtn.style.fontWeight = '700';
        stopBtn.disabled = true;
        stopBtn.style.opacity = '0.6';

        startBtn.addEventListener('click', () => {
            showConfigModal(() => {
                startBtn.disabled = true;
                stopBtn.disabled = false;
                stopBtn.style.opacity = '1';

                isRunning = true;
                statusText.textContent = `Running | Collected: ${collectedLinks.size}/${TOTAL_TARGET}`;

                console.log('Scraper started.');
                scanAndScroll();
                scrollTimer = setInterval(scanAndScroll, SCROLL_INTERVAL);
            });
        });

        stopBtn.addEventListener('click', () => {
            stopBtn.style.opacity = '0.6';
            stopScraper(true);
        });

        buttonWrap.appendChild(startBtn);
        buttonWrap.appendChild(stopBtn);

        panel.appendChild(title);
        panel.appendChild(statusText);
        panel.appendChild(buttonWrap);

        document.body.appendChild(panel);
    }

    window.addEventListener('load', () => {
        setTimeout(createControlPanel, 3000);
    });
})();
