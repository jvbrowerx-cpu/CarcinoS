import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { supabase, DEMO_MODE } from '../lib/supabase';
import { registerForPushNotifications } from '../lib/notifications';

export default function RootLayout() {
  useEffect(() => {
    if (DEMO_MODE || !supabase) return;

    // Register for push notifications once the auth session is confirmed.
    // supabase.auth.getSession() resolves immediately from the persisted
    // session — no network round-trip needed on subsequent launches.
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        registerForPushNotifications().catch(console.warn);
      }
    });

    // Re-register whenever the user signs in (e.g. after OTP verify)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_IN') {
        registerForPushNotifications().catch(console.warn);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  return (
    <>
      <StatusBar style="light" />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" />
      </Stack>
    </>
  );
}
