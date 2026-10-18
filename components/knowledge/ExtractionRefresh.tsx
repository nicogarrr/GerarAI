'use client';
import {useEffect} from 'react';
import {useRouter} from 'next/navigation';
/** Refresh only while a known extraction is active; stop when terminal. */
export function ExtractionRefresh({active}: {active: boolean}) {
 const router=useRouter();
 useEffect(()=>{
  if(!active) return;
  const timer=window.setInterval(()=>{if(document.visibilityState==='visible')router.refresh();},10000);
  return ()=>window.clearInterval(timer);
 },[active,router]);
 return null;
}
