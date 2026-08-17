import { createHmac, timingSafeEqual } from 'crypto';
import type {
	IHookFunctions,
	IWebhookFunctions,
	INodeType,
	INodeTypeDescription,
	IWebhookResponseData,
	IHttpRequestMethods,
	IDataObject,
} from 'n8n-workflow';

/**
 * Omni event trigger.
 *
 * On activation it registers this n8n webhook URL as an Omni outbound webhook
 * subscription (POST /webhook-subscriptions) for the chosen event types and
 * stores the returned signing secret. On each delivery it verifies the
 * X-Omni-Signature HMAC before emitting the event. On deactivation it deletes
 * the subscription (DELETE /webhook-subscriptions/{id}).
 */
export class OmniTrigger implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Omni Trigger',
		name: 'omniTrigger',
		icon: 'file:omni.svg',
		group: ['trigger'],
		version: 1,
		subtitle: '={{ $parameter["events"].join(", ") }}',
		description: 'Starts a workflow when an Omni domain event fires',
		defaults: {
			name: 'Omni Trigger',
		},
		inputs: [],
		outputs: ['main'],
		credentials: [
			{
				name: 'omniApi',
				required: true,
			},
		],
		webhooks: [
			{
				name: 'default',
				httpMethod: 'POST',
				responseMode: 'onReceived',
				path: 'webhook',
			},
		],
		properties: [
			{
				displayName: 'Events',
				name: 'events',
				type: 'multiOptions',
				required: true,
				default: [],
				description: 'Which Omni events should trigger this workflow (empty = all supported)',
				options: [
					{ name: 'Campaign Run Completed', value: 'campaign.run.completed' },
					{ name: 'Hot Lead', value: 'lead.hot' },
					{ name: 'Invite Accepted', value: 'invite.accepted' },
					{ name: 'Lead Enriched', value: 'lead.enriched' },
					{ name: 'Lead Replied', value: 'lead.replied' },
				],
			},
		],
	};

	webhookMethods = {
		default: {
			async checkExists(this: IHookFunctions): Promise<boolean> {
				const webhookData = this.getWorkflowStaticData('node');
				return webhookData.subscriptionId !== undefined;
			},

			async create(this: IHookFunctions): Promise<boolean> {
				const webhookUrl = this.getNodeWebhookUrl('default') as string;
				const events = this.getNodeParameter('events', []) as string[];
				const credentials = await this.getCredentials('omniApi');
				const baseUrl = (credentials.apiBaseUrl as string).replace(/\/$/, '');

				const body: IDataObject = { url: webhookUrl, event_types: events };
				const response = (await this.helpers.httpRequestWithAuthentication.call(
					this,
					'omniApi',
					{
						method: 'POST' as IHttpRequestMethods,
						url: `${baseUrl}/webhook-subscriptions`,
						body,
						json: true,
					},
				)) as IDataObject;

				const webhookData = this.getWorkflowStaticData('node');
				webhookData.subscriptionId = response.id as string;
				webhookData.secret = (response.secret as string) ?? '';
				return true;
			},

			async delete(this: IHookFunctions): Promise<boolean> {
				const webhookData = this.getWorkflowStaticData('node');
				if (webhookData.subscriptionId === undefined) {
					return true;
				}
				const credentials = await this.getCredentials('omniApi');
				const baseUrl = (credentials.apiBaseUrl as string).replace(/\/$/, '');
				try {
					await this.helpers.httpRequestWithAuthentication.call(this, 'omniApi', {
						method: 'DELETE' as IHttpRequestMethods,
						url: `${baseUrl}/webhook-subscriptions/${webhookData.subscriptionId}`,
						json: true,
					});
				} catch {
					// Already gone on the server — treat as deleted.
				}
				delete webhookData.subscriptionId;
				delete webhookData.secret;
				return true;
			},
		},
	};

	async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
		const req = this.getRequestObject();
		const headers = this.getHeaderData() as IDataObject;
		const webhookData = this.getWorkflowStaticData('node');
		const secret = (webhookData.secret as string) ?? '';

		// Verify the HMAC signature if we hold a secret for this subscription.
		if (secret) {
			const signatureHeader = (headers['x-omni-signature'] as string) ?? '';
			const raw =
				(req as unknown as { rawBody?: Buffer }).rawBody ??
				Buffer.from(JSON.stringify(this.getBodyData()));
			const expected = 'sha256=' + createHmac('sha256', secret).update(raw).digest('hex');
			const a = Buffer.from(signatureHeader);
			const b = Buffer.from(expected);
			if (a.length !== b.length || !timingSafeEqual(a, b)) {
				return { noWebhookResponse: true };
			}
		}

		return {
			workflowData: [this.helpers.returnJsonArray(this.getBodyData() as IDataObject)],
		};
	}
}
