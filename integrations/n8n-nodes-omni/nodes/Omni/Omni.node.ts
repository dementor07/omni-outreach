import type { INodeType, INodeTypeDescription } from 'n8n-workflow';

/**
 * Omni action node.
 *
 * Declarative (routing-based) node mapping 1:1 to the Omni public API
 * (/public/v1/*):
 *   Contact  → Create, List
 *   Campaign → Run
 *   Lead     → Enrich, Find, List
 *
 * Auth comes from the OmniApi credential (Authorization: Bearer <apiKey>).
 */
export class Omni implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Omni',
		name: 'omni',
		icon: 'file:omni.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{ $parameter["operation"] + ": " + $parameter["resource"] }}',
		description: 'Outbound outreach + CRM actions on Omni',
		defaults: {
			name: 'Omni',
		},
		inputs: ['main'],
		outputs: ['main'],
		credentials: [
			{
				name: 'omniApi',
				required: true,
			},
		],
		requestDefaults: {
			baseURL: '={{ $credentials.apiBaseUrl }}',
			headers: {
				'Content-Type': 'application/json',
			},
		},
		properties: [
			{
				displayName: 'Resource',
				name: 'resource',
				type: 'options',
				noDataExpression: true,
				options: [
					{ name: 'Contact', value: 'contact' },
					{ name: 'Campaign', value: 'campaign' },
					{ name: 'Lead', value: 'lead' },
				],
				default: 'contact',
			},

			// ── Contact operations ────────────────────────────────────────────
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: { show: { resource: ['contact'] } },
				options: [
					{
						name: 'Create',
						value: 'create',
						action: 'Create a contact',
						routing: {
							request: {
								method: 'POST',
								url: '/public/v1/contacts',
							},
						},
					},
					{
						name: 'List',
						value: 'list',
						action: 'List contacts',
						routing: {
							request: {
								method: 'GET',
								url: '/public/v1/contacts',
							},
						},
					},
				],
				default: 'create',
			},

			// ── Campaign operations ───────────────────────────────────────────
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: { show: { resource: ['campaign'] } },
				options: [
					{
						name: 'Run',
						value: 'run',
						action: 'Run a campaign',
						routing: {
							request: {
								method: 'POST',
								url: '=/public/v1/campaigns/{{ $parameter["campaignId"] }}/run',
							},
						},
					},
				],
				default: 'run',
			},

			// ── Lead operations ───────────────────────────────────────────────
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: { show: { resource: ['lead'] } },
				options: [
					{
						name: 'Enrich',
						value: 'enrich',
						action: 'Enrich a lead',
						routing: {
							request: {
								method: 'POST',
								url: '/public/v1/enrich',
							},
						},
					},
					{
						name: 'Find',
						value: 'find',
						action: 'Find leads',
						routing: {
							request: {
								method: 'POST',
								url: '/public/v1/leads/find',
							},
						},
					},
					{
						name: 'List',
						value: 'list',
						action: 'List leads',
						routing: {
							request: {
								method: 'GET',
								url: '/public/v1/leads',
							},
						},
					},
				],
				default: 'find',
			},

			// ── Contact: Create fields ────────────────────────────────────────
			{
				displayName: 'Email',
				name: 'email',
				type: 'string',
				default: '',
				placeholder: 'ada@example.com',
				description: 'Contact email (email or LinkedIn URL required)',
				displayOptions: { show: { resource: ['contact'], operation: ['create'] } },
				routing: { send: { type: 'body', property: 'email' } },
			},
			{
				displayName: 'LinkedIn URL',
				name: 'linkedinUrl',
				type: 'string',
				default: '',
				description: 'Contact LinkedIn URL (email or LinkedIn URL required)',
				displayOptions: { show: { resource: ['contact'], operation: ['create'] } },
				routing: { send: { type: 'body', property: 'linkedin_url' } },
			},
			{
				displayName: 'Additional Fields',
				name: 'additionalFields',
				type: 'collection',
				placeholder: 'Add Field',
				default: {},
				displayOptions: { show: { resource: ['contact'], operation: ['create'] } },
				options: [
					{
						displayName: 'Company',
						name: 'company',
						type: 'string',
						default: '',
						routing: { send: { type: 'body', property: 'company' } },
					},
					{
						displayName: 'First Name',
						name: 'first_name',
						type: 'string',
						default: '',
						routing: { send: { type: 'body', property: 'first_name' } },
					},
					{
						displayName: 'Headline',
						name: 'headline',
						type: 'string',
						default: '',
						routing: { send: { type: 'body', property: 'headline' } },
					},
					{
						displayName: 'Last Name',
						name: 'last_name',
						type: 'string',
						default: '',
						routing: { send: { type: 'body', property: 'last_name' } },
					},
					{
						displayName: 'Phone',
						name: 'phone',
						type: 'string',
						default: '',
						routing: { send: { type: 'body', property: 'phone' } },
					},
				],
			},

			// ── Campaign: Run field ───────────────────────────────────────────
			{
				displayName: 'Campaign ID',
				name: 'campaignId',
				type: 'string',
				required: true,
				default: '',
				description: 'The workflow/campaign UUID to run',
				displayOptions: { show: { resource: ['campaign'], operation: ['run'] } },
			},

			// ── Lead: Enrich fields ───────────────────────────────────────────
			{
				displayName: 'Lead (JSON)',
				name: 'leadJson',
				type: 'json',
				default: '{\n  "email": "ada@example.com"\n}',
				description: 'The one-off lead payload to enrich',
				displayOptions: { show: { resource: ['lead'], operation: ['enrich'] } },
				routing: { send: { type: 'body', property: 'lead' } },
			},
			{
				displayName: 'Enrich Source',
				name: 'enrichSource',
				type: 'string',
				default: 'apollo',
				displayOptions: { show: { resource: ['lead'], operation: ['enrich'] } },
				routing: { send: { type: 'body', property: 'enrich_source' } },
			},
			{
				displayName: 'Connection Name',
				name: 'enrichConnection',
				type: 'string',
				default: '',
				description: 'The Omni connection whose credential the enrichment uses',
				displayOptions: { show: { resource: ['lead'], operation: ['enrich'] } },
				routing: { send: { type: 'body', property: 'connection_name' } },
			},

			// ── Lead: Find fields ─────────────────────────────────────────────
			{
				displayName: 'Query',
				name: 'inputData',
				type: 'string',
				default: '',
				placeholder: 'Heads of Growth at Series-B fintechs in the UK',
				description: 'Natural-language audience query',
				displayOptions: { show: { resource: ['lead'], operation: ['find'] } },
				routing: { send: { type: 'body', property: 'input_data' } },
			},
			{
				displayName: 'Finder Type',
				name: 'finderType',
				type: 'string',
				default: 'leads_finder_ai',
				displayOptions: { show: { resource: ['lead'], operation: ['find'] } },
				routing: { send: { type: 'body', property: 'finder_type' } },
			},
			{
				displayName: 'Connection Name',
				name: 'findConnection',
				type: 'string',
				default: '',
				displayOptions: { show: { resource: ['lead'], operation: ['find'] } },
				routing: { send: { type: 'body', property: 'connection_name' } },
			},
			{
				displayName: 'Fetch Count',
				name: 'fetchCount',
				type: 'number',
				default: 25,
				typeOptions: { minValue: 1, maxValue: 100 },
				displayOptions: { show: { resource: ['lead'], operation: ['find'] } },
				routing: { send: { type: 'body', property: 'fetch_count' } },
			},

			// ── List paging (contacts + leads) ────────────────────────────────
			{
				displayName: 'Limit',
				name: 'limit',
				type: 'number',
				default: 50,
				typeOptions: { minValue: 1 },
				description: 'Max number of results to return',
				displayOptions: { show: { resource: ['contact', 'lead'], operation: ['list'] } },
				routing: { send: { type: 'query', property: 'limit' } },
			},
			{
				displayName: 'Offset',
				name: 'offset',
				type: 'number',
				default: 0,
				typeOptions: { minValue: 0 },
				displayOptions: { show: { resource: ['contact', 'lead'], operation: ['list'] } },
				routing: { send: { type: 'query', property: 'offset' } },
			},
		],
	};
}
