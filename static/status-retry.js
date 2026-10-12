(() => {
  const originalFetch = window.fetch.bind(window);
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function isStatusRequest(input) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    return url.includes('/api/deploy-status/') || url.includes('/api/undeploy-status/');
  }

  window.fetch = async function novecFetch(input, init) {
    if (!isStatusRequest(input)) return originalFetch(input, init);

    let lastResponse = null;
    let lastError = null;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        const response = await originalFetch(input, init);
        lastResponse = response;
        if (![502, 503, 504].includes(response.status)) return response;
      } catch (error) {
        lastError = error;
      }
      await delay(1250 + attempt * 250);
    }

    if (lastResponse) return lastResponse;
    throw lastError || new Error('Temporary status connection failure');
  };
})();
