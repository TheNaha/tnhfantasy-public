import { useState, useEffect } from 'react';

let subscribers = [];
let interval = null;

const notify = () => {
  const now = Date.now();
  subscribers.forEach((cb) => cb(now));
};

export default function useGlobalClock(enabled = true) {
  const [time, setTime] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) return;
    
    subscribers.push(setTime);
    if (!interval && subscribers.length > 0) {
      interval = setInterval(notify, 1000);
    }
    
    return () => {
      subscribers = subscribers.filter(cb => cb !== setTime);
      if (subscribers.length === 0 && interval) {
        clearInterval(interval);
        interval = null;
      }
    };
  }, [enabled]);

  return time;
}
