<script context="module" lang="ts">
	export type ResearchStatus = {
		action?: string; toolCallId?: string; done?: boolean; hidden?: boolean;
		description?: string; urls?: string[]; query?: string; queries?: string[]; count?: number;
		items?: { link: string; title?: string }[];
		activity?: { title: string; state: string; elapsed?: number; detail?: string; summary?: string;
			items?: { url?: string; title?: string; note?: string }[] };
	};
	type Activity = NonNullable<ResearchStatus['activity']> & { id: string };
</script>

<script lang="ts">
	export let statusHistory: ResearchStatus[] = [];
	export let messageDone = false;
	let expanded = true;
	$: activities = Array.from(statusHistory.reduce((calls, entry) => {
		if (entry.action === 'workstation_tool' && entry.toolCallId && entry.activity) {
			calls.set(entry.toolCallId, { ...entry.activity, id: entry.toolCallId });
		}
		return calls;
	}, new Map<string, Activity>()).values());
	$: ended = messageDone || statusHistory.at(-1)?.done === true;
	$: running = activities.filter((item) => item.state === 'running').length;
	const labels: Record<string, string> = { running: '执行中', completed: '已完成', failed: '失败', partial: '部分完成', interrupted: '未收到完成回执' };
	const label = (state: string) => labels[state] || state;
	const link = (value?: string) => {
		try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
		catch { return ''; }
	};
</script>

{#if activities.length}
	<section class="my-2 rounded-xl border border-gray-200 dark:border-gray-700 text-sm" aria-label="研究过程">
		<button class="w-full p-3 text-left font-medium" aria-expanded={expanded} on:click={() => expanded = !expanded}>
			研究过程 · {activities.length} 项操作{#if running && !ended} · {running} 项执行中{:else if ended} · 本轮已结束{/if}
			<span class="float-right">{expanded ? '收起' : '展开'}</span>
		</button>
		{#if expanded}
			<ol class="px-3 pb-3 space-y-3 max-h-[32rem] overflow-y-auto">
				{#each activities as activity (activity.id)}
					<li class="border-t border-gray-200 dark:border-gray-700 pt-2 break-words">
						<div class="font-medium">{activity.title}
							<span class="text-xs font-normal text-gray-500"> · {label(ended && activity.state === 'running' ? 'interrupted' : activity.state)}{#if activity.elapsed !== undefined} · {activity.elapsed} 秒{/if}</span>
						</div>
						{#if activity.detail}<div class="text-gray-600 dark:text-gray-300 whitespace-pre-wrap">{activity.detail}</div>{/if}
						{#if activity.summary}<div class="mt-1">{activity.summary}</div>{/if}
						{#if activity.items?.length}
							<ul class="mt-1 space-y-1 pl-4 list-disc">
								{#each activity.items as item}
									<li>{#if link(item.url)}<a class="underline" href={link(item.url)} target="_blank" rel="noopener noreferrer">{item.title || item.url}</a>{:else}{item.title}{/if}
										{#if item.note}<div class="text-xs text-gray-500">{item.note}</div>{/if}
									</li>
								{/each}
							</ul>
						{/if}
					</li>
				{/each}
			</ol>
		{/if}
	</section>
{/if}
