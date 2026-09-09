import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import "./styles.css";
import "./i18n"; /* resolves ?lang= / localStorage locale, sets <html lang> before first paint */

createApp(App).use(createPinia()).mount("#app");
