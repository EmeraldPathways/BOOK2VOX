import type { ReactNode } from "react";
export const metadata = { title: "BOOK2VOX", description: "Expressive AI audiobook studio" };
export default function Layout({children}:{children:ReactNode}) { return <html lang="en"><body style={{margin:0,background:"#111716",color:"#f2f1eb",fontFamily:"Arial,sans-serif"}}>{children}</body></html> }
