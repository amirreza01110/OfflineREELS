// ==UserScript==
// @name         Instagram Reels Link Scraper (Robust Scroll)
// @namespace    http://tampermonkey.net/
// @version      1.2
// @description  Scrolls Instagram Reels using DOM navigation, extracts video links, and saves them in batches.
// @author       YourName
// @match        https://www.instagram.com/reels/*
// @match        https://www.instagram.com/reels/
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    // --- Configuration ---
    const BATCH_SIZE = 10;       // Number of links per file
    const SCROLL_INTERVAL = 4500; // Time in ms between scrolls (gives video/links time to load)
    // ---------------------

    let collectedLinks = new Set();
    let currentBatch = [];
    let fileCounter = 0;
    let scrollTimer = null;

    // Trigger the file download
    function downloadBatch(links, index) {
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
        console.log(`Saved: ${index}.txt`);
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
        // 1. Try to find the currently playing video
        const activeVideo = document.querySelector('video');
        if (!activeVideo) {
            // Fallback: If no video is playing yet, try basic keyboard dispatch
            dispatchArrowDown(document.activeElement || document);
            return;
        }

        // 2. Find the container card of the active video (usually an <article> or parent wrapper)
        const currentCard = activeVideo.closest('article') || activeVideo.closest('[role="presentation"]');
        if (currentCard) {
            // Find all cards loaded in the feed
            const cards = Array.from(document.querySelectorAll('article, [role="presentation"]'));
            const currentIndex = cards.indexOf(currentCard);

            if (currentIndex !== -1 && currentIndex + 1 < cards.length) {
                // Scroll the next card into view smoothly
                cards[currentIndex + 1].scrollIntoView({ behavior: 'smooth', block: 'start' });
                return;
            }
        }

        // 3. Fallback: If DOM traversal fails, try keyboard dispatch on the video's parent
        dispatchArrowDown(activeVideo.parentElement);
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

    // Main collection logic
    function scanAndScroll() {
        const anchors = document.querySelectorAll('a');

        anchors.forEach(anchor => {
            const href = anchor.href;
            if (!href) return;

            const cleanUrl = href.split('?')[0].split('#')[0];

            if (isValidReelUrl(cleanUrl)) {
                if (!collectedLinks.has(cleanUrl)) {
                    collectedLinks.add(cleanUrl);
                    currentBatch.push(cleanUrl);
                    console.log(`Added: ${cleanUrl} (${currentBatch.length}/${BATCH_SIZE})`);

                    if (currentBatch.length >= BATCH_SIZE) {
                        downloadBatch(currentBatch, fileCounter);
                        fileCounter++;
                        currentBatch = [];
                    }
                }
            }
        });

        // Trigger the scroll to the next video
        scrollToNextReel();
    }

    // UI Control Panel
    function createControlPanel() {
        const panel = document.createElement('div');
        panel.style.position = 'fixed';
        panel.style.bottom = '20px';
        panel.style.right = '20px';
        panel.style.zIndex = '99999';
        panel.style.padding = '12px';
        panel.style.backgroundColor = '#1a1a1a';
        panel.style.color = '#fff';
        panel.style.border = '1px solid #333';
        panel.style.borderRadius = '8px';
        panel.style.fontFamily = 'sans-serif';
        panel.style.boxShadow = '0 4px 12px rgba(0,0,0,0.5)';

        const startBtn = document.createElement('button');
        startBtn.textContent = 'Start Scraping';
        startBtn.style.marginRight = '8px';
        startBtn.style.padding = '6px 12px';
        startBtn.style.cursor = 'pointer';

        const stopBtn = document.createElement('button');
        stopBtn.textContent = 'Stop';
        stopBtn.style.padding = '6px 12px';
        stopBtn.style.cursor = 'pointer';
        stopBtn.disabled = true;

        startBtn.addEventListener('click', () => {
            startBtn.disabled = true;
            stopBtn.disabled = false;
            console.log("Scraper started.");
            scanAndScroll();
            scrollTimer = setInterval(scanAndScroll, SCROLL_INTERVAL);
        });

        stopBtn.addEventListener('click', () => {
            startBtn.disabled = false;
            stopBtn.disabled = true;
            clearInterval(scrollTimer);
            console.log("Scraper stopped.");

            if (currentBatch.length > 0) {
                if (confirm(`Do you want to save the remaining ${currentBatch.length} links?`)) {
                    downloadBatch(currentBatch, fileCounter);
                    fileCounter++;
                    currentBatch = [];
                }
            }
        });

        panel.appendChild(startBtn);
        panel.appendChild(stopBtn);
        document.body.appendChild(panel);
    }

    window.addEventListener('load', () => {
        setTimeout(createControlPanel, 3000);
    });
})();
