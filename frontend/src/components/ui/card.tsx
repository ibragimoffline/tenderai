import * as React from 'react'

import { cn } from '@/lib/utils'

// KARTA.
//
// SOYA YO'Q — chuqurlik SIRT va CHEGARA bilan beriladi (`bg-card`
// `--background` dan bir pog'ona baland + 1px `border`). Bu tugmalarda
// allaqachon qabul qilingan qoida (`button.tsx` ga qarang), lekin
// kartaga o'tkazilmay qolgan edi: natijada bitta ekranda soyasiz tugma
// va soyali karta yonma-yon turardi.
//
// Zich ish quroli uchun bu ayniqsa muhim: ekranda o'nlab karta bo'ladi
// va har birining ostidagi soya shovqinga aylanadi. Suzuvchi qatlamlar
// (`popover`, `sheet`, `confirm-dialog`, `select`) soyani SAQLAYDI —
// ular haqiqatan kontent USTIDA turadi va buni bildirishi kerak.
function Card({ className, ...props }: React.ComponentProps<'div'>) {
    return (
        <div
            data-slot="card"
            className={cn('bg-card text-card-foreground rounded-xl border', className)}
            {...props}
        />
    )
}

function CardHeader({ className, ...props }: React.ComponentProps<'div'>) {
    return (
        <div
            data-slot="card-header"
            className={cn('flex flex-col gap-1.5 p-6', className)}
            {...props}
        />
    )
}

function CardTitle({ className, ...props }: React.ComponentProps<'div'>) {
    return (
        <div
            data-slot="card-title"
            className={cn('font-semibold leading-none tracking-tight', className)}
            {...props}
        />
    )
}

function CardDescription({ className, ...props }: React.ComponentProps<'div'>) {
    return (
        <div
            data-slot="card-description"
            className={cn('text-muted-foreground text-body', className)}
            {...props}
        />
    )
}

function CardContent({ className, ...props }: React.ComponentProps<'div'>) {
    return (
        <div
            data-slot="card-content"
            className={cn('p-6 pt-0', className)}
            {...props}
        />
    )
}

function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
    return (
        <div
            data-slot="card-footer"
            className={cn('flex items-center p-6 pt-0', className)}
            {...props}
        />
    )
}

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent }
